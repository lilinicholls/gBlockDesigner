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
import re
import threading
import time
import urllib.parse
import urllib.request
import uuid
from io import StringIO
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
MAX_CONCURRENT_BLAST_JOBS = 3
_BLAST_SEMAPHORE = threading.Semaphore(MAX_CONCURRENT_BLAST_JOBS)

# How long a finished job's result is kept around before being cleaned up,
# so the in-memory store doesn't grow forever on a long-running deployment.
JOB_RETENTION_SECONDS = 60 * 60

BLAST_URL = "https://blast.ncbi.nlm.nih.gov/blast/Blast.cgi"
POLL_SECONDS = 10          # NCBI asks for no more than one status check per 10s per search
MAX_WAIT_SECONDS = 6 * 60   # give up (with a clear message) rather than spin forever

# NCBI's full "nt" is enormous and slow to search; "core_nt" is their
# faster, non-redundant default for the website and returns the same
# kind of hits for this use.
DATABASE_ALIASES = {"nt": "core_nt"}

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


class NCBIWaitError(RuntimeError):
    """NCBI accepted the search but didn't finish it (too slow, or it failed).
    Raised on purpose so we do NOT start a second search as a "fallback"."""


def _http(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "gBlockDesigner"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fast_blast_xml(sequence: str, program: str, database: str, job_id: str = None) -> str:
    """Submits the search and checks on it every 10 seconds, returning the
    XML result as soon as NCBI has it. (Biopython's built-in qblast only
    checks once a MINUTE after the first 20s, so a search that finished
    after 25s would not be noticed until ~80s; it also uses the slower
    non-megablast algorithm and asks for 500 alignments by default.)"""
    params = {
        "CMD": "Put", "PROGRAM": program, "DATABASE": database, "QUERY": sequence,
        "HITLIST_SIZE": MAX_HITS_TO_FETCH, "ALIGNMENTS": MAX_HITS_TO_FETCH,
        "DESCRIPTIONS": MAX_HITS_TO_FETCH, "FORMAT_TYPE": "XML", "TOOL": "gBlockDesigner",
    }
    if program == "blastn":
        params["MEGABLAST"] = "on"
    if os.environ.get("NCBI_EMAIL"):
        params["EMAIL"] = os.environ["NCBI_EMAIL"]
    page = _http(BLAST_URL, urllib.parse.urlencode(params).encode())
    rid = re.search(r"RID = (\S+)", page)
    if not rid:
        raise RuntimeError("NCBI did not return a search ID")
    rid = rid.group(1)
    if job_id:
        _set_job(job_id, rid=rid, database=database)
    rtoe = re.search(r"RTOE = (\d+)", page)
    time.sleep(min(int(rtoe.group(1)) if rtoe else POLL_SECONDS, POLL_SECONDS))

    waited = 0
    while waited < MAX_WAIT_SECONDS:
        info = _http(f"{BLAST_URL}?CMD=Get&FORMAT_OBJECT=SearchInfo&RID={rid}")
        status = re.search(r"Status=(\w+)", info)
        status = status.group(1) if status else "UNKNOWN"
        if status == "READY":
            return _http(f"{BLAST_URL}?CMD=Get&FORMAT_TYPE=XML&RID={rid}")
        if status in ("FAILED", "UNKNOWN"):
            raise NCBIWaitError(f"NCBI reported the search as {status.lower()}.")
        time.sleep(POLL_SECONDS)
        waited += POLL_SECONDS
    raise NCBIWaitError("NCBI is taking too long to answer (over 6 minutes). Use the \"NCBI's own BLAST page\" link instead, or try again later.")


def _run_blast(job_id: str, sequence: str, program: str, database: str):
    _set_job(job_id, status="waiting_for_slot")
    with _BLAST_SEMAPHORE:
        try:
            _set_job(job_id, status="running", started_at=datetime.now(timezone.utc).isoformat())

            database = DATABASE_ALIASES.get(database, database)
            try:
                xml = _fast_blast_xml(sequence, program, database, job_id)
                record = NCBIXML.read(StringIO(xml))
            except NCBIWaitError:
                raise  # the search was accepted but is slow or failed: don't start another one
            except Exception:  # noqa: BLE001 - submission itself failed: fall back to Biopython's route
                result_handle = NCBIWWW.qblast(
                    program, database, sequence, hitlist_size=MAX_HITS_TO_FETCH,
                    alignments=MAX_HITS_TO_FETCH, descriptions=MAX_HITS_TO_FETCH,
                    megablast=True if program == "blastn" else None,
                )
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
