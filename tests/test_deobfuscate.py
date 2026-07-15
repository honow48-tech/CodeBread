import json

from codebread.deobfuscate import safe_eval_int_expr, scan_obfuscation


# ---------------- safety boundary: the whole point of this module ----------

def test_safe_eval_refuses_variables():
    assert safe_eval_int_expr("x >> 3") is None


def test_safe_eval_refuses_function_calls():
    assert safe_eval_int_expr("foo() >> 3") is None
    assert safe_eval_int_expr('__import__("os")') is None


def test_safe_eval_refuses_attribute_access():
    assert safe_eval_int_expr("os.system") is None


def test_safe_eval_refuses_floats():
    assert safe_eval_int_expr("3.5 + 1") is None


def test_safe_eval_refuses_garbage():
    assert safe_eval_int_expr("not valid python !!! at all") is None
    assert safe_eval_int_expr("") is None
    assert safe_eval_int_expr("   ") is None


def test_safe_eval_computes_plain_arithmetic():
    assert safe_eval_int_expr("545259520>>23") == 65
    assert safe_eval_int_expr("65 + 1") == 66
    assert safe_eval_int_expr("65*2-64") == 66
    assert safe_eval_int_expr("(1+1)*33") == 66


def test_safe_eval_handles_c_style_leading_zero_octal():
    # 0144 isn't valid Python-3 literal syntax (needs 0o144) — must still
    # resolve, since PHP/Ruby/Go/legacy-JS all write octal this way.
    assert safe_eval_int_expr("0144") == 100
    assert safe_eval_int_expr("0103") == 67


def test_safe_eval_never_raises_on_zero_division():
    assert safe_eval_int_expr("1/0") is None
    assert safe_eval_int_expr("1//0") is None


# ---------------- escape decoding -------------------------------------

def test_php_hex_and_octal_escapes():
    findings = scan_obfuscation(r'$x = "\x41\x42\154";', "php")
    assert len(findings) == 1
    assert findings[0].kind == "escape"
    assert findings[0].decoded == "ABl"


def test_php_single_quotes_are_not_escape_interpreted():
    # PHP single-quoted strings don't process \x/\NNN — must not "decode"
    # a literal backslash-x sequence that PHP itself would leave alone.
    findings = scan_obfuscation(r"$x = '\x41';", "php")
    assert findings == []


def test_javascript_hex_escapes_all_quote_styles():
    for quote in ('"', "'", "`"):
        text = f"var x = {quote}\\x41\\x42{quote};"
        findings = scan_obfuscation(text, "javascript")
        assert len(findings) == 1
        assert findings[0].decoded == "AB"


def test_javascript_unicode_brace_escape():
    findings = scan_obfuscation(r'var x = "\u{48}\u{49}";', "javascript")
    assert findings[0].decoded == "HI"


def test_python_hex_and_octal_escapes():
    findings = scan_obfuscation(r'x = "\x41\102"', "python")
    assert findings[0].decoded == "AB"


def test_java_octal_escape_no_hex():
    # Java has no \xHH escape at all — only confirm octal + no false hex hit.
    findings = scan_obfuscation(r'String s = "\101\102C";', "java")
    assert len(findings) == 1
    assert findings[0].decoded == "ABC"


def test_csharp_hex_escape_no_octal():
    findings = scan_obfuscation(r'string s = "\x41\x42C";', "csharp")
    assert findings[0].decoded == "ABC"


def test_go_hex_and_octal_escapes():
    findings = scan_obfuscation(r'x := "\x41\102C"', "go")
    assert findings[0].decoded == "ABC"


def test_ruby_hex_and_octal_escapes():
    findings = scan_obfuscation(r'x = "\x41\102C"', "ruby")
    assert findings[0].decoded == "ABC"


def test_escape_scan_ignores_normal_strings():
    assert scan_obfuscation('$x = "just a normal string";', "php") == []


# ---------------- char-code call decoding -------------------------------

def test_php_chr_with_bitshift_math():
    findings = scan_obfuscation("chr(545259520>>23);", "php")
    char_findings = [f for f in findings if f.kind == "char-code"]
    assert len(char_findings) == 1
    assert char_findings[0].decoded == "A"


def test_python_chr_call():
    findings = scan_obfuscation("x = chr(65) + chr(0146)", "python")
    decoded = [f.decoded for f in findings if f.kind == "char-code"]
    assert decoded == ["A", "f"]


def test_javascript_string_fromcharcode_multi_arg():
    findings = scan_obfuscation(
        "var s = String.fromCharCode(72, 101, 108, 108, 111);", "javascript")
    assert len(findings) == 1
    assert findings[0].decoded == "Hello"


def test_java_char_cast():
    findings = scan_obfuscation("char c = (char)(65+1);", "java")
    assert findings[0].decoded == "B"


def test_csharp_char_cast():
    findings = scan_obfuscation("char c = (char)(65*2-64);", "csharp")
    assert findings[0].decoded == "B"


def test_go_string_rune_cast():
    findings = scan_obfuscation("x := string(rune(65+1))", "go")
    assert findings[0].decoded == "B"


def test_ruby_dot_chr():
    findings = scan_obfuscation("x = (65+1).chr; y = 97.chr", "ruby")
    decoded = sorted(f.decoded for f in findings)
    assert decoded == ["B", "a"]


def test_charcode_with_variable_argument_is_left_alone():
    # chr($x) — not a literal, must not be "decoded" into a guess.
    assert scan_obfuscation("chr($x);", "php") == []


# ---------------- base64 decoding -------------------------------------

def test_php_base64_decode_readable_text():
    findings = scan_obfuscation(
        '$s = base64_decode("SGVsbG8sIHRoaXMgaXMgYSBoaWRkZW4gbWVzc2FnZS4=");', "php")
    b64 = [f for f in findings if f.kind == "base64"]
    assert len(b64) == 1
    assert b64[0].decoded == "Hello, this is a hidden message."


def test_javascript_atob():
    findings = scan_obfuscation('var s = atob("SGVsbG8gd29ybGQh");', "javascript")
    assert findings[0].decoded == "Hello world!"


def test_python_base64_b64decode():
    findings = scan_obfuscation(
        'x = base64.b64decode("SGVsbG8gd29ybGQh")', "python")
    assert findings[0].decoded == "Hello world!"


def test_base64_decode_of_binary_garbage_is_not_reported():
    # random short base64-alphabet text that decodes to non-printable bytes
    # shouldn't be surfaced as a "finding" — nothing readable to show.
    findings = scan_obfuscation('base64_decode("AAECAwQFBgcICQ==");', "php")
    assert findings == []


def test_base64_decode_credentials_get_masked_like_config_files():
    findings = scan_obfuscation(
        '$s = base64_decode("' +
        __import__("base64").b64encode(
            b"postgres://admin:hunter2@db.example.com/prod").decode() +
        '");', "php")
    assert len(findings) == 1
    assert "hunter2" not in findings[0].decoded
    assert "db.example.com" in findings[0].decoded


# ---------------- chaff (dead literal-statement) detection --------------

def test_php_chaff_statement_detected():
    text = '<?php\n"d"."=t*&".chr(545259520>>23).chr(721420288>>23);\n'
    findings = scan_obfuscation(text, "php")
    chaff = [f for f in findings if f.kind == "chaff"]
    assert len(chaff) == 1
    assert chaff[0].line == 2


def test_chaff_containing_equals_sign_in_literal_is_still_detected():
    # regression: a literal string *containing* "=" (not an assignment)
    # must not be excluded by a naive "contains =" check.
    text = '<?php\n"a=b"."c";\n'
    findings = scan_obfuscation(text, "php")
    assert any(f.kind == "chaff" for f in findings)


def test_assigned_literal_is_not_flagged_as_chaff():
    text = '<?php\n$x = "a"."b";\n'
    findings = scan_obfuscation(text, "php")
    assert not any(f.kind == "chaff" for f in findings)


def test_echoed_literal_is_not_flagged_as_chaff():
    text = '<?php\necho "a"."b";\n'
    findings = scan_obfuscation(text, "php")
    assert not any(f.kind == "chaff" for f in findings)


def test_function_call_argument_literal_is_not_flagged_as_chaff():
    text = '<?php\nsome_func("a"."b");\n'
    findings = scan_obfuscation(text, "php")
    assert not any(f.kind == "chaff" for f in findings)


def test_javascript_chaff_uses_plus_operator():
    text = '"noise" + "more noise" + String.fromCharCode(65);\n'
    findings = scan_obfuscation(text, "javascript")
    assert any(f.kind == "chaff" for f in findings)


def test_python_and_ruby_chaff_detection_not_attempted():
    # scoped out for v1 (see README): no reliable statement terminator to
    # anchor on without a real parser, so we deliberately report nothing
    # rather than guess and risk false positives.
    text = '"a" "b"\n'
    assert scan_obfuscation(text, "python") == []
    assert scan_obfuscation(text, "ruby") == []


# ---------------- unsupported / neutral languages ------------------------

def test_unrecognized_language_returns_no_findings():
    assert scan_obfuscation('chr(65);', "sql") == []
    assert scan_obfuscation('chr(65);', "unknown") == []


def test_scan_never_raises_on_malformed_input():
    # unbalanced parens / quotes shouldn't crash the scanner
    scan_obfuscation('chr(65', "php")
    scan_obfuscation('"unterminated', "php")
    scan_obfuscation('base64_decode(', "php")


# ---------------- lone-surrogate safety (real crash, found via a real file) -

def test_lone_surrogate_uni4_escape_is_left_undecoded():
    # \uD800-\uDFFF are UTF-16 surrogate halves, not standalone codepoints.
    # chr() will happily build one, but json.dumps(...).encode("utf-8")
    # later raises UnicodeEncodeError on it — this crashed a real scan.
    findings = scan_obfuscation(r'var x = "\uD800";', "javascript")
    assert findings == []


def test_lone_surrogate_charcode_call_is_left_undecoded():
    assert scan_obfuscation("String.fromCharCode(0xD800);", "javascript") == []
    assert scan_obfuscation("chr(0xD800);", "php") == []


def test_paired_surrogates_each_individually_still_left_undecoded():
    # a real astral character (e.g. an emoji) written as a JS surrogate
    # pair is two *separate* \u escapes to this scanner — each one is a
    # lone half on its own, so both correctly stay undecoded rather than
    # producing two unpaired surrogates.
    findings = scan_obfuscation(r'var x = "😀";', "javascript")
    assert findings == []


def test_every_finding_is_json_serializable_as_utf8():
    # the actual crash path: build_server() does
    # json.dumps(graph, ensure_ascii=False).encode("utf-8") over the whole
    # graph, including every decoded finding.
    samples = [
        (r'var x = "\uD800\x41";', "javascript"),
        ("chr(0xD800); chr(65);", "php"),
        ("String.fromCharCode(0xD800, 72, 105);", "javascript"),
    ]
    for text, lang in samples:
        findings = scan_obfuscation(text, lang)
        payload = [{"line": f.line, "kind": f.kind, "original": f.original,
                   "decoded": f.decoded} for f in findings]
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
