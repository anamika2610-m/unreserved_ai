"""
Simple hardcoded script to exercise ToneAdaptationService and see
how the SAME buyer question is answered under different tones.

Run with:
    source .venv/bin/activate
    python test_tone_adaptation_service.py
"""

from app.services.tone_adaptation_service import ToneAdaptationService, ToneLevel
from app.services.rag_pipeline.llms import create_chat_completion
from app.services.rag_pipeline.prompts import SYSTEM_PROMPT

# Same buyer question used for all tone cases
TEST_QUESTION = "what is the floor size of this property?"


def pretty_print_case(name: str, activity: dict, service: ToneAdaptationService) -> None:
    print("\n" + "=" * 80)
    print(f"CASE: {name}")
    print("=" * 80)
    print("Input listing_activity:")
    for k, v in activity.items():
        print(f"  - {k}: {v}")

    tone_level, tone_context = service.determine_tone(activity)

    formatted = service.format_tone_context_for_prompt(tone_level, tone_context)
    if formatted:
        user_prompt = f"{formatted.strip()}\n\n=== BUYER QUESTION ===\n{TEST_QUESTION}"
    else:
        user_prompt = f"=== BUYER QUESTION ===\n{TEST_QUESTION}"

    # Call the LLM once, similar to the main pipeline, to see an actual answer
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    response = create_chat_completion(
        messages=messages,
        model="gpt-4o",
        temperature=0.2,
        max_tokens=400,
    )
    answer = response.choices[0].message.content.strip()

    print(f"\nTone: {tone_level.value}")
    print(f"Question: {TEST_QUESTION}")
    print("Response:")
    print("-" * 80)
    print(answer)
    print("-" * 80)


def main() -> None:
    svc = ToneAdaptationService()

    # NOTE: These are synthetic metric combos crafted to trigger each tone
    # according to the priority:
    # 1. URGENT → 2. TIME_SENSITIVE → 3. COMPETITIVE → 4. DECISIVE → 5. CONFIDENT

    cases = {
        # Should pick URGENT (genuine_offers >= 2)
        "URGENT_from_offers": {
            "enquiries_7d": 5,
            "repeat_buyers_7d": 0,
            "first_inspection_groups_7d": 0,
            "multi_inspection_buyers_7d": 0,
            "contract_requests_7d": 1,
            "genuine_offers_7d": 4,
            "competing_offers_7d": 0,
            "bp_inspections_7d": 0,
            "property_type": "house",
        },
        # Should pick URGENT (B&P inspections >= 2) even if contracts are high
        "URGENT_from_bp_inspections": {
            "enquiries_7d": 10,
            "repeat_buyers_7d": 1,
            "first_inspection_groups_7d": 0,
            "multi_inspection_buyers_7d": 0,
            "contract_requests_7d": 5,  # would be time_sensitive, but urgent wins
            "genuine_offers_7d": 0,
            "competing_offers_7d": 0,
            "bp_inspections_7d": 3,
            "property_type": "apartment",
        },
        # Should pick TIME_SENSITIVE (contract_requests >= 3)
        "TIME_SENSITIVE": {
            "enquiries_7d": 8,
            "repeat_buyers_7d": 1,
            "first_inspection_groups_7d": 5,
            "multi_inspection_buyers_7d": 1,
            "contract_requests_7d": 3,
            "genuine_offers_7d": 1,
            "competing_offers_7d": 0,
            "bp_inspections_7d": 0,
            "property_type": "house",
        },
        # Should pick COMPETITIVE (inspection groups over threshold)
        "COMPETITIVE_from_inspections_house": {
            "enquiries_7d": 10,
            "repeat_buyers_7d": 2,
            "first_inspection_groups_7d": svc.HOUSE_INSPECTION_THRESHOLD + 1,
            "multi_inspection_buyers_7d": 0,
            "contract_requests_7d": 0,
            "genuine_offers_7d": 0,
            "competing_offers_7d": 0,
            "bp_inspections_7d": 0,
            "property_type": "house",
        },
        # Should also pick COMPETITIVE (multi_inspection_buyers_7d >= 3)
        "COMPETITIVE_from_multi_inspections": {
            "enquiries_7d": 5,
            "repeat_buyers_7d": 1,
            "first_inspection_groups_7d": 0,
            "multi_inspection_buyers_7d": 3,
            "contract_requests_7d": 0,
            "genuine_offers_7d": 0,
            "competing_offers_7d": 0,
            "bp_inspections_7d": 0,
            "property_type": "apartment",
        },
        # Should pick DECISIVE (competing_offers_7d >= 1) when no urgent/time_sensitive/competitive flags
        "DECISIVE": {
            "enquiries_7d": 6,
            "repeat_buyers_7d": 1,
            "first_inspection_groups_7d": 2,
            "multi_inspection_buyers_7d": 1,
            "contract_requests_7d": 0,
            "genuine_offers_7d": 1,
            "competing_offers_7d": 1,
            "bp_inspections_7d": 0,
            "property_type": "house",
        },
        # Should pick CONFIDENT (high enquiries or repeat buyers)
        "CONFIDENT_from_enquiries": {
            "enquiries_7d": svc.ENQUIRIES_HIGH_THRESHOLD + 3,
            "repeat_buyers_7d": 0,
            "first_inspection_groups_7d": 0,
            "multi_inspection_buyers_7d": 0,
            "contract_requests_7d": 0,
            "genuine_offers_7d": 0,
            "competing_offers_7d": 0,
            "bp_inspections_7d": 0,
            "property_type": "apartment",
        },
        "CONFIDENT_from_repeat_buyers": {
            "enquiries_7d": 5,
            "repeat_buyers_7d": 5,
            "first_inspection_groups_7d": 0,
            "multi_inspection_buyers_7d": 0,
            "contract_requests_7d": 0,
            "genuine_offers_7d": 0,
            "competing_offers_7d": 0,
            "bp_inspections_7d": 0,
            "property_type": "house",
        },
        # Should fall back to NEUTRAL
        "NEUTRAL": {
            "enquiries_7d": 2,
            "repeat_buyers_7d": 0,
            "first_inspection_groups_7d": 1,
            "multi_inspection_buyers_7d": 0,
            "contract_requests_7d": 0,
            "genuine_offers_7d": 0,
            "competing_offers_7d": 0,
            "bp_inspections_7d": 0,
            "property_type": "house",
        },
    }

    for name, activity in cases.items():
        pretty_print_case(name, activity, svc)


if __name__ == "__main__":
    main()

