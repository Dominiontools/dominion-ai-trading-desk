from engine.agents import AGENTS, get_agent, order_capable_agents

def test_eight_specialist_agents_are_registered():
    assert len(AGENTS) == 8
    assert get_agent("DESK_MANAGER").may_submit_orders is False

def test_no_agent_can_submit_orders_in_foundation_build():
    assert order_capable_agents() == ()
