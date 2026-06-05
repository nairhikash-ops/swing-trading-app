from app.ai_reviews import AiReviewStore
from app.demo_trading import DemoTradingService
from app.trading_journal import TradingJournalStore
from app.watchlist import WatchlistService
from test_demo_trading import seed_drishti_hit


def test_demo_journal_lists_automated_trade_with_outcome_metrics(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path)
    AiReviewStore(token_store)
    demo_service = DemoTradingService(settings, token_store)
    WatchlistService(settings, token_store, demo_service)
    trade = demo_service.place_order_from_drishti_hit(int(hit["id"]))
    journal = TradingJournalStore(token_store).journal()

    assert journal["summary"]["total_trades"] == 1
    assert journal["summary"]["closed_positions"] == 1
    assert journal["summary"]["winners"] == 1
    item = journal["items"][0]
    assert item["order_id"] == trade["order"]["id"]
    assert item["symbol"] == hit["symbol"]
    assert item["status"] == "closed"
    assert item["outcome_label"] == "winner"
    assert item["exit_reason"] == "TARGET"
    assert item["pnl"] > 0
    assert item["r_multiple"] is not None
    assert item["max_favorable_percent"] > 0


def test_demo_journal_notes_are_saved_by_order_id(tmp_path):
    settings, token_store, hit = seed_drishti_hit(tmp_path)
    AiReviewStore(token_store)
    demo_service = DemoTradingService(settings, token_store)
    WatchlistService(settings, token_store, demo_service)
    trade = demo_service.place_order_from_drishti_hit(int(hit["id"]))
    journal_store = TradingJournalStore(token_store)

    updated = journal_store.upsert_notes(
        int(trade["order"]["id"]),
        setup_notes="Clean Drishti reversal confirmation.",
        management_notes="Let the stop and target work.",
        mistake_notes="",
        tags=["drishti-s1", "auto"],
    )
    journal = journal_store.journal()

    assert updated["setup_notes"] == "Clean Drishti reversal confirmation."
    assert updated["tags"] == ["auto", "drishti-s1"]
    assert journal["items"][0]["management_notes"] == "Let the stop and target work."
