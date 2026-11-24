from engine.agent_feeds import DexScreenerDiscovery, GeckoTerminalWhaleFeed, GoPlusSecurityFeed, PublicNewsRSS

def test_dexscreener_discovers_token_and_enriches_pair():
    def fake(url, timeout, **kwargs):
        if url.endswith("/token-profiles/latest/v1"):
            return [{"chainId":"ethereum","tokenAddress":"0xabc","description":"test"}]
        return [{"baseToken":{"symbol":"ABC","name":"Alpha"},"pairAddress":"0xpool",
                 "priceUsd":"0.5","liquidity":{"usd":50000},"volume":{"h24":12000},
                 "txns":{"h24":{"buys":12,"sells":3}},"pairCreatedAt":1700000000000,"url":"https://dex"}]
    rows=DexScreenerDiscovery(fetch_json=fake).discover()
    assert rows[0]["symbol"]=="ABC" and rows[0]["liquidity_usd"]==50000

def test_geckoterminal_normalizes_whale_trade():
    def fake(url, timeout, **kwargs):
        return {"data":[{"attributes":{"volume_in_usd":"150000","kind":"buy",
                "block_timestamp":"2026-11-24T10:00:00Z","tx_from_address":"0xwallet","tx_hash":"0xhash"}}]}
    rows=GeckoTerminalWhaleFeed(fetch_json=fake).trades("eth","0xpool","ABC")
    assert rows[0]["side"]=="BUY" and rows[0]["notional_usd"]==150000

def test_goplus_uses_free_tier_without_token():
    calls = []
    def fake(url, timeout, **kwargs):
        calls.append(kwargs.get("headers", {}))
        return {"code":1,"result":{"0xabc":{"is_honeypot":"0","is_open_source":"1"}}}
    result=GoPlusSecurityFeed(fetch_json=fake).assess("ethereum","0xabc")
    assert result["status"]=="DATA_RETURNED_REQUIRES_REVIEW"
    assert calls == [{}]

def test_goplus_flags_honeypot_and_missing_fields_not_safe():
    calls = []
    def fake(url, timeout, **kwargs):
        calls.append(kwargs.get("headers", {}))
        return {"code":1,"result":{"0xabc":{"is_honeypot":"1","is_open_source":"0"}}}
    result=GoPlusSecurityFeed(fetch_json=fake,token="test-token").assess("ethereum","0xabc")
    assert calls == [{"Authorization":"Bearer test-token"}]
    assert "HONEYPOT" in result["risks"]
    assert "UNVERIFIED_CONTRACT" in result["risks"]

def test_public_rss_parses_headlines():
    xml="<rss><channel><item><title>Bitcoin bullish adoption</title><description>growth</description><pubDate>today</pubDate></item></channel></rss>"
    rows=PublicNewsRSS(fetch_text=lambda url,timeout:xml).headlines()
    assert len(rows)==1 and "bullish" in rows[0]["text"]
