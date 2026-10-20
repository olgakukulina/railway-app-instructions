"""Самопроверка adapter.py: python test_adapter.py"""

from adapter import _clean_ai_text, latex_to_text, normalize_table, strip_emphasis


def test_latex_to_text():
    assert latex_to_text(r"$K = \frac{N(4i+1)}{200} + \frac{7N}{200}$") == "K = (N(4i+1))/200 + 7N/200"
    assert latex_to_text(r"\[ K = \left\lceil \frac{n \cdot (4i + 1)}{200} \right\rceil \]") == "K = ⌈(n · (4i + 1))/200⌉"
    assert latex_to_text(r"$v \leq 3\,\text{км/ч}$, $i_{max} = 2{,}5\permil$") == "v ≤ 3 км/ч, iₘₐₓ = 2,5‰"
    assert latex_to_text(r"площадь $S = a^2$, $x^{n+1}$, $T_{расч}$") == "площадь S = a², xⁿ⁺¹, T_(расч)"
    assert latex_to_text(r"\(\sqrt{a^2 + b^2}\)") == "√(a² + b²)"
    assert latex_to_text("Обычный текст ~ без формул.") == "Обычный текст ~ без формул."


def test_strip_emphasis():
    assert strip_emphasis("**Важно:** закрепление *обязательно*, __всегда__ и _везде_.") == \
        "Важно: закрепление обязательно, всегда и везде."
    assert strip_emphasis("K = (N*(4*i+1))/200") == "K = (N·(4·i+1))/200"
    assert strip_emphasis("## Заголовок\nтекст") == "Заголовок\nтекст"
    assert strip_emphasis("путь_необщего пользования") == "путь_необщего пользования"


def test_clean_ai_text():
    text = "4.1. Нормы\n\n**Расчёт** по формуле $K = \\frac{7N}{200}$, где *N* — число осей."
    assert _clean_ai_text(text) == "4.1. Нормы\nРасчёт по формуле K = 7N/200, где N — число осей."


def test_normalize_table():
    assert normalize_table({"headers": ["a", "b"], "rows": [["1", None, 3, 4], [], [None, ""], ["x"]]}) == {
        "headers": ["a", "b", "", ""], "rows": [["1", "", "3", "4"], ["x", "", "", ""]]}
    assert normalize_table({"headers": [], "rows": [[None]]}) is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
