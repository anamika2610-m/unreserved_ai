"""
Test script to demonstrate Google Maps amenity links feature.
Shows how the backend generates amenity links for the frontend.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.rag_pipeline.google_maps_links import (
    generate_context_aware_links,
    generate_amenity_links,
    detect_amenity_query,
    AMENITY_TYPES
)
import json


def test_amenity_detection():
    """Test amenity query detection."""
    print("=" * 70)
    print("TEST 1: Amenity Query Detection")
    print("=" * 70)
    
    test_queries = [
        "Are there any hospitals nearby?",
        "What about schools and supermarkets?",
        "Tell me about nearby bus stops and parks",
        "Is there a gym close by?",
        "What's the price of this property?"  # No amenity
    ]
    
    for query in test_queries:
        detected = detect_amenity_query(query)
        print(f"Query: {query}")
        print(f"Detected: {detected if detected else 'None'}\n")


def test_link_generation():
    """Test Google Maps link generation."""
    print("\n" + "=" * 70)
    print("TEST 2: Google Maps Link Generation")
    print("=" * 70)
    
    # Sydney coordinates (45 Park Lane)
    latitude = -33.8688
    longitude = 151.2093
    
    # Generate links for specific amenities
    links = generate_amenity_links(
        latitude=latitude,
        longitude=longitude,
        amenity_types=["hospitals", "schools", "bus_stops"]
    )
    
    print(f"\nGenerated {len(links)} amenity links:")
    print(json.dumps(links, indent=2))


def test_context_aware_generation():
    """Test context-aware link generation."""
    print("\n" + "=" * 70)
    print("TEST 3: Context-Aware Link Generation")
    print("=" * 70)
    
    # Melbourne coordinates (12 Green Park)
    latitude = -37.8136
    longitude = 144.9631
    
    # User asks about hospitals
    query = "Are there any hospitals nearby?"
    
    result = generate_context_aware_links(
        query=query,
        latitude=latitude,
        longitude=longitude,
        include_common=True
    )
    
    print(f"\nQuery: {query}")
    print(f"\nRelevant Links (user asked about):")
    for link in result['relevant_links']:
        print(f"  {link['icon']} {link['label']}")
        print(f"     URL: {link['url']}\n")
    
    print(f"Suggested Links (commonly useful):")
    for link in result['suggested_links'][:3]:  # Show first 3
        print(f"  {link['icon']} {link['label']}")
        print(f"     URL: {link['url']}\n")


def test_all_amenities():
    """Show all available amenity types."""
    print("\n" + "=" * 70)
    print("TEST 4: All Available Amenity Types")
    print("=" * 70)
    
    print("\nSupported Amenities:")
    for amenity_type, config in AMENITY_TYPES.items():
        print(f"{config['icon']} {config['label']} ({amenity_type})")


def test_frontend_integration():
    """Show how frontend would use this data."""
    print("\n" + "=" * 70)
    print("TEST 5: Frontend Integration Example")
    print("=" * 70)
    
    # Simulate API response
    latitude = -33.8688
    longitude = 151.2093
    query = "Are there any hospitals and schools nearby?"
    
    result = generate_context_aware_links(query, latitude, longitude)
    
    print("\n📤 Backend sends to Frontend:")
    print(json.dumps({
        "answer": "Based on the property location...",
        "nearby_properties": [],
        "amenity_links": result['all_links']
    }, indent=2))
    
    print("\n\n📥 Frontend renders as:")
    print("\n┌─────────────────────────────────────────┐")
    print("│  Explore Nearby Amenities              │")
    print("└─────────────────────────────────────────┘")
    
    for link in result['all_links'][:4]:  # Show first 4
        print(f"\n  [{link['icon']} {link['label']}]")
        print(f"  Button/Link → {link['url']}")


def main():
    """Run all tests."""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 10 + "Google Maps Amenity Links - Test Suite" + " " * 19 + "║")
    print("╚" + "=" * 68 + "╝")
    
    test_amenity_detection()
    test_link_generation()
    test_context_aware_generation()
    test_all_amenities()
    test_frontend_integration()
    
    print("\n" + "=" * 70)
    print("✅ All tests completed!")
    print("=" * 70)
    print("\nNow test with real queries:")
    print("  1. Run: python scripts/chat_listing_cli.py")
    print("  2. Enter listing: prop-similar-001")
    print("  3. Ask: 'Are there any hospitals nearby?'")
    print("  4. See amenity links in the output! 🗺️")
    print()


if __name__ == "__main__":
    main()

