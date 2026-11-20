"""Queue scheduled crawls and due scheduled posts (approved content only). Run from cron, e.g. every 5-15 minutes:  python -m app.services.web.scheduler"""
from app.core.db import SessionLocal
from app.services.web.competitor_monitor import due_jobs
from app.services.web.runner import run_crawl_job


def main() -> int:
    db = SessionLocal()
    try:
        jobs = due_jobs(db)
        from app.worker import queue
        q = queue()
        for j in jobs:
            q.enqueue(run_crawl_job, j.id, job_timeout=3600)
        print(f"queued {len(jobs)} scheduled crawl(s)")
        from app.services.marketing.publishing_service import due_jobs as due_posts, run_publishing_job
        posts = due_posts(db)
        for p in posts:
            q.enqueue(run_publishing_job, p.id, job_timeout=600)
        print(f"queued {len(posts)} scheduled post(s)")
        return len(jobs) + len(posts)
    finally:
        db.close()


if __name__ == "__main__":
    main()
