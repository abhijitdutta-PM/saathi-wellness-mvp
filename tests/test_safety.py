from app.safety import assess_text, safe_buddy_fallback, urgent_support_message


def test_direct_self_harm_statement_routes_to_immediate_review():
    result = assess_text("I want to die and I don't know what to do.")
    assert result.urgency == "immediate"
    assert result.create_case is True
    assert result.category == "self_harm_or_suicide"


def test_possible_bullying_routes_to_human_review():
    result = assess_text("Some classmates are bullying me every day.")
    assert result.urgency == "human_review"
    assert result.create_case is True


def test_ordinary_upset_does_not_automatically_open_case():
    result = assess_text("I feel worried about tomorrow's test.")
    assert result.urgency == "routine"
    assert result.create_case is False


def test_repeated_distress_routes_for_check_in():
    result = assess_text("I feel lonely lately.", recent_distress_count=2)
    assert result.urgency == "human_review"
    assert result.category == "recurring_distress"


def test_demo_fallback_is_supportive_not_diagnostic():
    reply = safe_buddy_fallback("I feel sad about an argument with a friend.", "11-14")
    assert "I'm glad" in reply
    assert "diagnos" not in reply.lower()


def test_urgent_message_never_promises_instant_human_response():
    reply = urgent_support_message("Demo only")
    assert "cannot guarantee an immediate human response" in reply
    assert "trusted adult" in reply
