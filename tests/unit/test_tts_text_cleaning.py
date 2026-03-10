"""
Unit tests for TTS text cleaning functionality in postprocess.py.
"""
import re


def clean_text_for_tts(text: str) -> str:
    """
    Clean text for Text-to-Speech output.
    Removes HTML, converts markdown links to readable text, and removes 
    raw URLs to ensure natural-sounding TTS output.
    
    Args:
        text: The raw text from AI response
        
    Returns:
        Cleaned text suitable for TTS
    """
    if not text:
        return text
    
    cleaned = text
    
    # 1. Remove HTML tags
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    
    # 2. Convert markdown links [text](url) to "text link"
    # Pattern matches [anchor text](URL)
    cleaned = re.sub(
        r'\[([^\]]+)\]\([^)]+\)',
        r'\1 link',
        cleaned
    )
    
    # 3. Remove raw URLs (http, https, www patterns)
    # Matches http://, https://, www. followed by domain
    url_pattern = r'(?:https?://|www\.)[^\s\)>\]\'"]+'
    cleaned = re.sub(url_pattern, 'link', cleaned)
    
    # 4. Remove markdown formatting while keeping content
    # Bold: **text** or __text__ → text
    cleaned = re.sub(r'\*\*([^\*]+)\*\*', r'\1', cleaned)
    cleaned = re.sub(r'__([^_]+)__', r'\1', cleaned)
    
    # Italic: *text* or _text_ → text (but not already bold)
    cleaned = re.sub(r'(?<!\*)\*([^\*]+)\*(?!\*)', r'\1', cleaned)
    cleaned = re.sub(r'(?<!_)_([^_]+)_(?!_)', r'\1', cleaned)
    
    # 5. Remove markdown headers (# Header → Header)
    cleaned = re.sub(r'^#+\s*', '', cleaned, flags=re.MULTILINE)
    
    # 6. Remove markdown list markers (- item → item)
    cleaned = re.sub(r'^[\-\*]\s+', '', cleaned, flags=re.MULTILINE)
    
    # 7. Remove markdown blockquotes (> quote → quote)
    cleaned = re.sub(r'^>\s*', '', cleaned, flags=re.MULTILINE)
    
    # 8. Clean up extra whitespace
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = re.sub(r' {2,}', ' ', cleaned)
    
    # 9. Remove any remaining markdown link remnants (in case of edge cases)
    cleaned = re.sub(r'\[([^\]]*)\](?!\()', r'\1', cleaned)
    
    return cleaned.strip()


def test_markdown_link_conversion():
    """Test markdown links [text](url) are converted to readable text."""
    test_cases = [
        ("[View property](https://example.com)", "View property link"),
        ("[Click here](http://test.com/page)", "Click here link"),
        ("[Multiple words link](https://example.com/path)", "Multiple words link link"),
    ]
    
    for input_text, expected in test_cases:
        result = clean_text_for_tts(input_text)
        assert result == expected, f"Expected '{expected}', got '{result}'"


def test_raw_url_removal():
    """Test raw URLs are removed."""
    test_cases = [
        ("Check https://example.com for info", "Check link for info"),
        ("Visit www.test.com now", "Visit link now"),
        ("https://google.com is a search engine", "link is a search engine"),
    ]
    
    for input_text, expected in test_cases:
        result = clean_text_for_tts(input_text)
        assert result == expected, f"Expected '{expected}', got '{result}'"


def test_bold_formatting_removal():
    """Test markdown bold formatting is removed."""
    test_cases = [
        ("The **price** is $500k", "The price is $500k"),
        ("This is __bold__ text", "This is bold text"),
        ("**Important** information", "Important information"),
    ]
    
    for input_text, expected in test_cases:
        result = clean_text_for_tts(input_text)
        assert result == expected, f"Expected '{expected}', got '{result}'"


def test_italic_formatting_removal():
    """Test markdown italic formatting is removed."""
    test_cases = [
        ("This is *italic* text", "This is italic text"),
        ("_Underlined_ works too", "Underlined works too"),
    ]
    
    for input_text, expected in test_cases:
        result = clean_text_for_tts(input_text)
        assert result == expected, f"Expected '{expected}', got '{result}'"


def test_html_tag_removal():
    """Test HTML tags are removed."""
    test_cases = [
        ("<p>Hello world</p>", "Hello world"),
        ("<strong>Bold</strong> text", "Bold text"),
        ("<a href='http://test.com'>Link</a>", "Link"),
    ]
    
    for input_text, expected in test_cases:
        result = clean_text_for_tts(input_text)
        assert result == expected, f"Expected '{expected}', got '{result}'"


def test_header_removal():
    """Test markdown headers are simplified."""
    test_cases = [
        ("# Main Title", "Main Title"),
        ("## Section", "Section"),
        ("### Subsection", "Subsection"),
    ]
    
    for input_text, expected in test_cases:
        result = clean_text_for_tts(input_text)
        assert result == expected, f"Expected '{expected}', got '{result}'"


def test_list_removal():
    """Test markdown list markers are removed."""
    test_cases = [
        ("- First item", "First item"),
        ("* Second item", "Second item"),
    ]
    
    for input_text, expected in test_cases:
        result = clean_text_for_tts(input_text)
        assert result == expected, f"Expected '{expected}', got '{result}'"


def test_real_world_examples():
    """Test with realistic AI response examples."""
    # Example 1: AI response with links
    input1 = "You can [view the property here](https://example.com/property) for more details."
    expected1 = "You can view the property here link for more details."
    assert clean_text_for_tts(input1) == expected1
    
    # Example 2: AI response with bold and links
    input2 = "The **asking price** is $500,000. Check [this link](https://example.com) for more info."
    expected2 = "The asking price is $500,000. Check this link link for more info."
    assert clean_text_for_tts(input2) == expected2
    
    # Example 3: AI response with raw URL
    input3 = "For more information, visit https://example.com or contact us."
    expected3 = "For more information, visit link or contact us."
    assert clean_text_for_tts(input3) == expected3


def test_empty_and_none():
    """Test edge cases with empty/None input."""
    assert clean_text_for_tts("") == ""
    assert clean_text_for_tts("   ") == ""
    assert clean_text_for_tts("No special formatting") == "No special formatting"


def test_preserves_normal_text():
    """Test that normal text without formatting is preserved."""
    text = "This is a normal sentence without any special formatting."
    assert clean_text_for_tts(text) == text


if __name__ == "__main__":
    print("Running TTS text cleaning tests...")
    
    tests = [
        test_markdown_link_conversion,
        test_raw_url_removal,
        test_bold_formatting_removal,
        test_italic_formatting_removal,
        test_html_tag_removal,
        test_header_removal,
        test_list_removal,
        test_real_world_examples,
        test_empty_and_none,
        test_preserves_normal_text,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            print(f"✓ {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: Unexpected error: {e}")
            failed += 1
    
    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
