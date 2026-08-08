from __future__ import annotations

__all__ = ["symbol_glyph_name"]

# Adobe Symbol encoding. The names are interpreted through the Adobe Glyph
# List shipped by fontTools. Keeping the encoding data here avoids depending
# on a proprietary Symbol font binary. Codes 0x7F-0x9F are undefined.
_SYMBOL_LOW_NAMES: tuple[str, ...] = (
    "space", "exclam", "universal", "numbersign", "existential", "percent",
    "ampersand", "suchthat", "parenleft", "parenright", "asteriskmath", "plus",
    "comma", "minus", "period", "slash", "zero", "one", "two", "three",
    "four", "five", "six", "seven", "eight", "nine", "colon", "semicolon",
    "less", "equal", "greater", "question", "congruent", "Alpha", "Beta",
    "Chi", "Delta", "Epsilon", "Phi", "Gamma", "Eta", "Iota", "theta1",
    "Kappa", "Lambda", "Mu", "Nu", "Omicron", "Pi", "Theta", "Rho",
    "Sigma", "Tau", "Upsilon", "sigma1", "Omega", "Xi", "Psi", "Zeta",
    "bracketleft", "therefore", "bracketright", "perpendicular", "underscore",
    "radicalex", "alpha", "beta", "chi", "delta", "epsilon", "phi", "gamma",
    "eta", "iota", "phi1", "kappa", "lambda", "mu", "nu", "omicron", "pi",
    "theta", "rho", "sigma", "tau", "upsilon", "omega1", "omega", "xi",
    "psi", "zeta", "braceleft", "bar", "braceright", "similar",
)

_SYMBOL_HIGH_NAMES: tuple[str | None, ...] = (
    "Euro", "Upsilon1", "minute", "lessequal", "fraction", "infinity", "florin",
    "club", "diamond", "heart", "spade", "arrowboth", "arrowleft", "arrowup",
    "arrowright", "arrowdown", "degree", "plusminus", "second", "greaterequal",
    "multiply", "proportional", "partialdiff", "bullet", "divide", "notequal",
    "equivalence", "approxequal", "ellipsis", "arrowvertex", "arrowhorizex",
    "carriagereturn", "aleph", "Ifraktur", "Rfraktur", "weierstrass",
    "circlemultiply", "circleplus", "emptyset", "intersection", "union",
    "propersuperset", "reflexsuperset", "notsubset", "propersubset",
    "reflexsubset", "element", "notelement", "angle", "gradient",
    "registerserif", "copyrightserif", "trademarkserif", "product", "radical",
    "dotmath", "logicalnot", "logicaland", "logicalor", "arrowdblboth",
    "arrowdblleft", "arrowdblup", "arrowdblright", "arrowdbldown", "lozenge",
    "angleleft", "registersans", "copyrightsans", "trademarksans", "summation",
    "parenlefttp", "parenleftex", "parenleftbt", "bracketlefttp",
    "bracketleftex", "bracketleftbt", "bracelefttp", "braceleftmid",
    "braceleftbt", "braceex", None, "angleright", "integral", "integraltp",
    "integralex", "integralbt", "parenrighttp", "parenrightex", "parenrightbt",
    "bracketrighttp", "bracketrightex", "bracketrightbt", "bracerighttp",
    "bracerightmid", "bracerightbt",
)


def symbol_glyph_name(code: int) -> str | None:
    if 0x20 <= code <= 0x7E:
        return _SYMBOL_LOW_NAMES[code - 0x20]
    if 0xA0 <= code <= 0xFE:
        return _SYMBOL_HIGH_NAMES[code - 0xA0]
    return None
