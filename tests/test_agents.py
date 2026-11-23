from engine.agents import AGENTS, AgentStatus, DeskManager

def test_eight_specialist_agents_are_registered():
    assert len(AGENTS) == 8
    assert {agent.name for agent in AGENTS} >= {"SCANNER", "RISK", "SNIPER", "WHALE", "RUG", "EXIT", "HYPE", "DESK MANAGER"}

def test_desk_manager_cannot_route_live_orders():
    manager = DeskManager()
    assert manager.can_route_live_orders() is False

def test_sniper_is_not_marked_ready_by_default():
    sniper = next(agent for agent in AGENTS if agent.name == "SNIPER")
    assert sniper.status == AgentStatus.STAGED
