"""
Runs a BLAST search against NCBI's public QBLAST web API (the same backend
that powers https://blast.ncbi.nlm.nih.gov/). This is a free service, but:

- It's rate-limited and can take anywhere from ~30 seconds to several
  minutes per search depending on NCBI's queue.
- NCBI's own documentation for this API lists a contact email and a tool
  name as *recommended*, not required - unlike browsing blast.ncbi.nlm.nih.gov
  by hand (which needs no login at all), this is meant as a courtesy for
  automated scripts, so NCBI can reach out if one misbehaves, before
  blocking it outright. It isn't enforced by the API itself. If you set
  NCBI_EMAIL in .env, it's used; if not, requests are still sent (with a
  tool name identifying this app, but no email attached).
- Because this can be slow, jobs are run in a background thread and polled
  via job_id, rather than blocking an HTTP request for the whole search.
"""

import os
import threading
import uuid
from datetime import datetime, timezone

from Bio.Blast import NCBIWWW, NCBIXML

NCBIWWW.tool = "gBlockDesigner"
NCBIWWW.email = os.environ.get("NCBI_EMAIL") or None

# In-memory job store. Fine for a single-process deployment; a multi-worker
# production deployment needs a shared store (e.g. Redis) instead - see
# README for details.
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()

# Since this can be a publicly-reachable app with no login, nothing stops
# many visitors from submitting BLAST searches at once - which could get
# the app's shared identity rate-limited or blocked by NCBI for everyone.
# This caps how many searches run at the same time; anything beyond that
# waits its turn rather than firing off unboundedly.
MAX_CONCURRENT_BLAST_JOBS = 2
_BLAST_SEMAPHORE = threading.Semaphore(MAX_CONCURRENT_BLAST_JOBS)

# How long a finished job's result is kept around before being cleaned up,
# so the in-memory store doesn't grow forever on a long-running deployment.
JOB_RETENTION_SECONDS = 60 * 60

MAX_HITS_TO_FETCH = 50   # ask NCBI for more, so we can report an accurate total
MAX_HITS_TO_DISPLAY = 10  # but only show the best 10 in the app


def _set_job(job_id: str, **fields):
    with _JOBS_LOCK:
        _JOBS.setdefault(job_id, {}).update(fields)


def get_job(job_id: str) -> dict | None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def _cleanup_old_jobs():
    cutoff = datetime.now(timezone.utc).timestamp() - JOB_RETENTION_SECONDS
    with _JOBS_LOCK:
        stale = [
            jid for jid, job in _JOBS.items()
            if job.get("finished_at") and datetime.fromisoformat(job["finished_at"]).timestamp() < cutoff
        ]
        for jid in stale:
            del _JOBS[jid]


def _run_blast(job_id: str, sequence: str, program: str, database: str):
    _set_job(job_id, status="waiting_for_slot")
    with _BLAST_SEMAPHORE:
        try:
            _set_job(job_id, status="running", started_at=datetime.now(timezone.utc).isoformat())

            result_handle = NCBIWWW.qblast(program, database, sequence, hitlist_size=MAX_HITS_TO_FETCH)
            record = NCBIXML.read(result_handle)
            result_handle.close()

            query_length = len(sequence)
            hits = []
            for alignment in record.alignments:
                for hsp in alignment.hsps:
                    query_coverage = round(100 * (abs(hsp.query_end - hsp.query_start) + 1) / query_length, 2) if query_length else 0
                    hits.append({
                        "title": alignment.title,
                        "accession": alignment.accession,
                        "length": alignment.length,
                        "e_value": hsp.expect,
                        "identity": hsp.identities,
                        "align_length": hsp.align_length,
                        "percent_identity": round(100 * hsp.identities / hsp.align_length, 2) if hsp.align_length else 0,
                        "query_coverage_percent": query_coverage,
                        "query_start": hsp.query_start,
                        "query_end": hsp.query_end,
                    })
                    break  # just the best HSP per alignment, to keep this readable

            # Sort by e-value ascending (most significant first)
            hits.sort(key=lambda h: h["e_value"])

            total_hits_found = len(hits)
            top_hits = hits[:MAX_HITS_TO_DISPLAY]

            _set_job(
                job_id,
                status="done",
                finished_at=datetime.now(timezone.utc).isoformat(),
                hits=top_hits,
                total_hits_found=total_hits_found,
                no_significant_hits=total_hits_found == 0,
            )
        except Exception as exc:  # noqa: BLE001 - surface any failure to the frontend
            _set_job(job_id, status="error", error=str(exc), finished_at=datetime.now(timezone.utc).isoformat())


def start_blast_job(sequence: str, program: str = "blastn", database: str = "nt") -> str:
    _cleanup_old_jobs()
    job_id = str(uuid.uuid4())
    _set_job(job_id, status="queued", sequence_length=len(sequence))
    thread = threading.Thread(target=_run_blast, args=(job_id, sequence, program, database), daemon=True)
    thread.start()
    return job_id
