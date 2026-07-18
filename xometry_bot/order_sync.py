"""Pure policy helpers for reliable incremental order synchronization."""

from __future__ import annotations

from collections.abc import Iterable


def select_order_links(
    links: Iterable[str],
    seen_order_ids: set[str],
    *,
    page_number: int,
    process_only_new: bool,
    refresh_recent_pages: int,
) -> tuple[list[str], list[str]]:
    links = list(dict.fromkeys(links))
    new_links = [link for link in links if link.rstrip("/").split("/")[-1] not in seen_order_ids]
    if not process_only_new or page_number <= max(0, refresh_recent_pages):
        return links, new_links
    return new_links, new_links


def should_persist_seen_state(*, records_sent: int, backend_accepted: bool) -> bool:
    """Never mark newly discovered orders as seen after a rejected/failed ingestion."""
    return records_sent == 0 or backend_accepted
