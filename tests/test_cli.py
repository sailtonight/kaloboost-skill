import datetime
import json

from conftest import err, page

from kaloboost.cli import main
from kaloboost.commands import common
from kaloboost.commands.order import merge_orders


def run(capsys, *argv):
    code = main(list(argv))
    return code, capsys.readouterr().out


# --- setup & usage -------------------------------------------------------------

def test_home_without_key(capsys, monkeypatch, tmp_path):
    monkeypatch.delenv("KALODATA_API_KEY", raising=False)
    monkeypatch.setenv("KALODATA_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("KALOBOOST_NO_UPDATE_CHECK", "1")
    code, out = run(capsys)
    assert code == 0
    assert "commands[" in out
    assert "auth: not configured" in out
    assert "open-center/account" in out


def test_key_is_read_from_shared_kalodata_config(capsys, monkeypatch, tmp_path, mock_server):
    monkeypatch.delenv("KALODATA_API_KEY", raising=False)
    monkeypatch.setenv("KALODATA_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("KALOBOOST_NO_UPDATE_CHECK", "1")
    monkeypatch.setenv("KALOBOOST_BASE_URL", f"http://127.0.0.1:{mock_server.server_address[1]}")
    (tmp_path / "config.toml").write_text('api_key = "from-kalo"\nregion = "GB"\n')
    code, _ = run(capsys, "capabilities")
    assert code == 0
    assert mock_server.requests[0][3]["secret-key"] == "from-kalo"


def test_config_set_keeps_kalo_keys(capsys, env, tmp_path):
    path = tmp_path / "cfg" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text('api_key = "k"\nregion = "GB"\n')
    code, _ = run(capsys, "config", "set", "--shop", "shop_1", "--env", "test")
    assert code == 0
    text = path.read_text()
    assert 'region = "GB"' in text and 'api_key = "k"' in text
    assert 'boost_shop = "shop_1"' in text
    assert "testopen.kaloboost.com" in text


def test_unknown_flag_exits_2(capsys, env):
    code, out = run(capsys, "sample", "list", "--shop", "s", "--stat", "x")
    assert code == 2
    assert out.startswith("error: unknown flag --stat")
    assert "--since" in out


def test_shop_required(capsys, env):
    code, out = run(capsys, "sample", "list")
    assert code == 2
    assert "--shop is required" in out
    assert "boost shops" in out
    assert env.requests == []


def test_default_shop_from_config(capsys, env, monkeypatch):
    monkeypatch.setenv("KALOBOOST_SHOP", "shop_cfg")
    run(capsys, "sample")  # bare noun runs `sample list`
    assert env.requests[0][2]["shop_id"] == "shop_cfg"


# --- time windows ----------------------------------------------------------------

def test_parse_when_forms():
    now = datetime.datetime(2026, 10, 8, 12, 30, 15, 999, tzinfo=datetime.timezone.utc)
    assert common.parse_when("7d", now=now) == "2026-10-01T12:30:15Z"
    assert common.parse_when("24h", now=now) == "2026-10-07T12:30:15Z"
    assert common.parse_when("2026-09-01") == "2026-09-01T00:00:00Z"
    assert common.parse_when("2026-09-01T08:00:00+08:00") == "2026-09-01T00:00:00Z"


def test_order_window_over_90_days_is_rejected(capsys, env):
    code, out = run(capsys, "order", "list", "--shop", "s", "--from", "2026-01-01", "--to", "2026-06-01")
    assert code == 2
    assert "longer than 90 days" in out
    assert env.requests == []


# --- happy paths -----------------------------------------------------------------

def test_shops_table_and_headers(capsys, env):
    env.responses["/shops"] = page(
        [{"shop_id": "806", "shop_name": "Demo, Shop", "shop_region": "US", "time_zone": None,
          "capabilities": ["OUTREACH", "SAMPLE"]}]
    )
    code, out = run(capsys, "shops")
    assert code == 0
    assert "shops[1]{shop_id,shop_name,region,time_zone,capabilities}:" in out
    assert '"806","Demo, Shop",US,null,OUTREACH|SAMPLE' in out
    method, path, query, headers, _ = env.requests[0]
    assert (method, path) == ("GET", "/shops")
    assert headers["secret-key"] == "test-key"
    assert headers["source-type"] == "SKILL"
    assert headers["user-agent"].startswith("boost/")  # Cloudflare blocks urllib's default UA
    assert query["limit"] == "50"


def test_more_hint_resends_shop_and_since(capsys, env):
    env.responses["/outreach-tasks"] = page([{"outreach_task_id": "t1", "status": "RUNNING"}], cursor="CUR1")
    code, out = run(capsys, "outreach", "list", "--shop", "s1", "--since", "2026-09-01")
    assert code == 0
    assert "More: `boost outreach list --shop s1 --since 2026-09-01T00:00:00Z --cursor CUR1`" in out
    assert env.requests[0][2]["updated_from"] == "2026-09-01T00:00:00Z"


def test_all_follows_cursor_resending_filters(capsys, env):
    env.responses["/outreach-tasks"] = [
        page([{"outreach_task_id": "t1"}], cursor="C1"),
        page([{"outreach_task_id": "t2"}], cursor=None),
    ]
    code, out = run(capsys, "outreach", "list", "--shop", "s1", "--since", "2026-09-01", "--all")
    assert code == 0
    assert "outreach_tasks[2]" in out
    second = env.requests[1][2]
    assert second["cursor"] == "C1"
    assert second["shop_id"] == "s1" and second["updated_from"] == "2026-09-01T00:00:00Z"
    assert "More:" not in out


def test_collab_empty_page_with_cursor_keeps_paging_and_dedupes(capsys, env):
    env.responses["/collaborations"] = [
        page([{"outreach_cooperate_id": "1", "cooperate_status": "NOT_COOPERATED", "updated_at": "2026-09-01T00:00:00Z"}], cursor="A"),
        page([], cursor="B"),
        page([{"outreach_cooperate_id": "1", "cooperate_status": "COOPERATED", "updated_at": "2026-09-02T00:00:00Z"}], cursor=None),
    ]
    code, out = run(capsys, "collab", "list", "--shop", "s", "--all")
    assert code == 0
    assert len(env.requests) == 3
    assert "collaborations[1]" in out
    assert "COOPERATED" in out and "NOT_COOPERATED" not in out
    assert "1 duplicate rows merged" in out


def test_samples_stop_on_empty_page(capsys, env):
    env.responses["/samples"] = [
        page([{"sample_request_id": "s1", "curr_status": "SHIPPED", "fulfillment": {"video_count": 2}}], cursor="X"),
        page([], cursor="Y"),
    ]
    code, out = run(capsys, "sample", "list", "--shop", "s", "--all")
    assert code == 0
    assert len(env.requests) == 2
    assert "samples[1]" in out
    assert "SHIPPED 1" in out


def test_sample_get_reports_merged_id(capsys, env):
    env.responses["/samples/old_id"] = {"data": {"sample_request_id": "new_id", "curr_status": "COMPLETED"}}
    code, out = run(capsys, "sample", "get", "old_id", "--shop", "s")
    assert code == 0
    assert "old_id was merged into new_id" in out


def test_orders_merge_items_across_pages():
    rows = [
        {"channel_order_id": "o1", "items": [{"channel_sku_id": "a"}]},
        {"channel_order_id": "o1", "items": [{"channel_sku_id": "b"}]},
        {"channel_order_id": "o2", "items": [{"channel_sku_id": "c"}]},
    ]
    merged = merge_orders(rows)
    assert [o["channel_order_id"] for o in merged] == ["o1", "o2"]
    assert [i["channel_sku_id"] for i in merged[0]["items"]] == ["a", "b"]
    assert len(rows[0]["items"]) == 1  # input untouched


def test_order_list_totals(capsys, env):
    item = {
        "channel_product_id": "p", "quantity": 2,
        "price": {"amount": "38", "currency": "USD"},
        "creator": {"username": "lind"},
        "content": {"type": "VIDEO", "channel_content_id": "755"},
        "commission": {"rate": "0.08", "estimated": {"paid": {"amount": "3.04", "currency": "USD"}}},
        "settlement_status": "TO_SETTLE", "fully_returned": False,
    }
    env.responses["/affiliate-orders"] = page([{"channel_order_id": "o1", "created_at": "2026-09-20T08:15:30Z", "items": [item]}])
    code, out = run(capsys, "order", "list", "--shop", "s", "--from", "2026-09-01", "--to", "2026-09-29")
    assert code == 0
    assert "1 orders, 1 SKU lines · GMV 76 USD · est. commission 3.04 USD" in out
    q = env.requests[0][2]
    assert q["created_from"] == "2026-09-01T00:00:00Z" and q["created_to"] == "2026-09-29T00:00:00Z"


def test_creator_resolve_builds_items(capsys, env):
    env.responses["/creator-identities/resolve"] = {"data": {"results": [
        {"external_request_id": "@demo", "status": "MATCHED", "match_basis": "EXACT_HANDLE_FALLBACK",
         "creator": {"creator_oecuid": "cr_1", "handle": "demo", "gmv_range": "$1K-$10K"}},
        {"external_request_id": "7491234567890123456", "status": "NOT_FOUND", "match_basis": "NONE"},
    ]}}
    code, out = run(capsys, "creator", "resolve", "@demo", "7491234567890123456", "--region", "gb")
    assert code == 0
    items = env.requests[0][4]["items"]
    assert items[0] == {"external_request_id": "@demo", "shop_region": "GB", "handle": "@demo"}
    assert items[1]["creator_user_id"] == "7491234567890123456"
    assert "cr_1" in out
    assert "NOT_FOUND only searched region GB" in out


def test_creator_get_rejects_handles(capsys, env):
    code, out = run(capsys, "creator", "get", "@demo")
    assert code == 2
    assert "creator resolve" in out


def test_events_poll_hint_and_has_more(capsys, env):
    env.responses["/events"] = [
        page([{"event_id": "e1", "type": "sample.updated", "data": {"curr_status": "SHIPPED"}}], cursor="E1", has_more=True),
        page([], cursor="E2", has_more=False),
    ]
    code, out = run(capsys, "event", "list", "--shop", "s", "--types", "sample.updated", "--all")
    assert code == 0
    assert len(env.requests) == 2
    assert "SHIPPED" in out
    assert "boost event list --cursor E2" in out
    assert env.requests[0][2]["types"] == "sample.updated"


def test_event_cursor_alone_is_enough(capsys, env):
    run(capsys, "event", "list", "--cursor", "E9")
    q = env.requests[0][2]
    assert q["cursor"] == "E9" and "shop_id" not in q


def test_json_output(capsys, env):
    env.responses["/capabilities"] = {"data": {"capabilities": {"sample": "PILOT"}}}
    code, out = run(capsys, "capabilities", "--json")
    assert code == 0
    assert json.loads(out) == {"capabilities": {"sample": "PILOT"}}


# --- errors ----------------------------------------------------------------------

def test_invalid_key(capsys, env):
    env.responses["/shops"] = err(401, "INVALID_API_KEY")
    code, out = run(capsys, "shops")
    assert code == 1
    assert out.startswith("error: INVALID_API_KEY")
    assert "request_id req_test" in out
    assert "paid plan" in out
    assert len(env.requests) == 1  # auth failures are not retried


def test_gateway_flat_error(capsys, env):
    # shape observed from open.kaloboost.com when secret-key is missing/invalid
    env.responses["/capabilities"] = (401, {"code": "INVALID_API_KEY", "message": "invalid secret-key", "request_id": "9347d259"})
    code, out = run(capsys, "capabilities")
    assert code == 1
    assert out.startswith("error: INVALID_API_KEY: invalid secret-key (request_id 9347d259)")
    assert "boost config set --key" in out


def test_shop_not_bound_hint(capsys, env):
    env.responses["/samples"] = err(403, "SHOP_NOT_AUTHORIZED", "shop_id", "SHOP_NOT_CURRENTLY_BOUND")
    code, out = run(capsys, "sample", "list", "--shop", "nope")
    assert code == 1
    assert "[shop_id/SHOP_NOT_CURRENTLY_BOUND]" in out
    assert "boost shops" in out


def test_capability_unavailable_not_retried(capsys, env):
    env.responses["/events"] = err(503, "CAPABILITY_UNAVAILABLE", "webhook", "PLANNED")
    code, out = run(capsys, "event", "list", "--shop", "s")
    assert code == 1
    assert len(env.requests) == 1
    assert "boost capabilities" in out


def test_upstream_503_is_retried(capsys, env):
    env.responses["/shops"] = [err(503, "UPSTREAM_UNAVAILABLE"), page([{"shop_id": "1"}])]
    code, out = run(capsys, "shops")
    assert code == 0
    assert len(env.requests) == 2


def test_rate_limit_waits_then_retries(capsys, env):
    limited = (429, {"error": {"code": "RATE_LIMITED", "details": []}}, {"Retry-After": "1"})
    env.responses["/shops"] = [limited, page([{"shop_id": "1"}])]
    code, _ = run(capsys, "shops")
    assert code == 0
    assert len(env.requests) == 2


def test_cursor_invalid_hint(capsys, env):
    env.responses["/samples"] = err(400, "INVALID_ARGUMENT", "cursor", "CURSOR_INVALID")
    code, out = run(capsys, "sample", "list", "--shop", "s", "--cursor", "bad")
    assert code == 1
    assert "Drop --cursor" in out


def test_affiliate_not_authorized(capsys, env):
    env.responses["/affiliate-orders"] = err(422, "CHANNEL_NOT_AVAILABLE", "shop_id", "SHOP_NOT_API_AUTHORIZED")
    code, out = run(capsys, "order", "list", "--shop", "s")
    assert code == 1
    assert "authorize TikTok Shop Open API" in out


def test_gateway_envelope_success_and_failure(capsys, env):
    env.responses["/capabilities"] = {"success": True, "data": {"data": {"capabilities": {"outreach": "PILOT"}}, "request_id": "r"}}
    code, out = run(capsys, "capabilities")
    assert code == 0 and "outreach,PILOT,true" in out
    env.responses["/shops"] = (401, {"success": False, "code": "401", "message": "invalid secret-key"})
    code, out = run(capsys, "shops")
    assert code == 1
    assert "invalid secret-key" in out
