"""
Product Registry -- DB-driven registry of fertilizer formulas and crop names.

Loads fertilizer data from mahbin_npk table at startup, generates lookup variants,
and provides matching (exact -> diacritics-stripped -> fuzzy) for user queries.

Data source: mahbin_npk table (19 rows, 6 crops)
Crops: นาข้าว, ข้าวโพด, อ้อย, มันสำปะหลัง, ปาล์มน้ำมัน, ยางพารา

Usage:
    registry = ProductRegistry.get_instance()
    await registry.load_from_db(supabase_client)
    product = registry.extract_product_name("ปุ๋ย 46-0-0 ใช้ยังไง")  # -> "46-0-0"
    product = registry.extract_product_name("ปุ๋ยนาข้าว")            # -> "นาข้าว"
"""

import logging
import re
import time
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Thai diacritics pattern (same as text_processing.py)
_THAI_DIACRITICS = re.compile(r'[\u0E48\u0E49\u0E4A\u0E4B\u0E47\u0E4C]')

# Pattern to match fertilizer formula strings like "46-0-0", "16-20-0", "0-0-60"
_FORMULA_PATTERN = re.compile(r'\b(\d{1,2})\s*[-\u2013]\s*(\d{1,2})\s*[-\u2013]\s*(\d{1,2})\b')


def _strip_diacritics(text: str) -> str:
    return _THAI_DIACRITICS.sub('', text)


def _generate_formula_variants(formula: str) -> List[str]:
    """
    Generate lookup variants for a fertilizer formula like "46-0-0".

    Variants:
    1. Original:       "46-0-0"
    2. No dashes:      "4600"
    3. With spaces:    "46 0 0"
    4. With dots:      "46.0.0"
    5. Lowercase (no-op for digits, but consistent)
    """
    variants = set()
    formula_lower = formula.strip().lower()
    variants.add(formula_lower)

    # Parse N-P-K components
    m = _FORMULA_PATTERN.match(formula_lower)
    if m:
        n, p, k = m.group(1), m.group(2), m.group(3)
        variants.add(f"{n}-{p}-{k}")          # canonical dash form
        variants.add(f"{n}{p}{k}")             # no separator
        variants.add(f"{n} {p} {k}")           # space separated
        variants.add(f"{n}.{p}.{k}")           # dot separated
        variants.add(f"{n}-{p}-{k}")           # ensure dash form

    # Also handle if dashes were en-dashes or other separators
    if '\u2013' in formula_lower:
        variants.add(formula_lower.replace('\u2013', '-'))

    return sorted(variants)


def _generate_crop_variants(crop_name: str) -> List[str]:
    """
    Generate lookup variants for a Thai crop name.

    Variants:
    1. Original lowercase
    2. Diacritics-stripped
    3. Common short forms / synonyms
    """
    variants = set()
    name_lower = crop_name.strip().lower()
    variants.add(name_lower)

    # Diacritics-stripped
    stripped = _strip_diacritics(name_lower)
    if stripped != name_lower:
        variants.add(stripped)

    return sorted(variants)


# =========================================================================
# Fallback data -- snapshot of mahbin_npk for offline / DB-unavailable use
# 6 crops, their fertilizer formulas, and common aliases
# =========================================================================
_FALLBACK_FORMULAS: Dict[str, List[str]] = {
    # Fertilizer formulas (canonical -> aliases/variants)
    "46-0-0":   ["46-0-0", "4600", "46 0 0", "46.0.0", "ยูเรีย", "urea"],
    "16-20-0":  ["16-20-0", "16200", "16 20 0", "16.20.0"],
    "18-46-0":  ["18-46-0", "18460", "18 46 0", "18.46.0", "dap", "แดป"],
    "0-0-60":   ["0-0-60", "0060", "0 0 60", "0.0.60", "โพแทสเซียม", "mop"],
    "15-15-15": ["15-15-15", "151515", "15 15 15", "15.15.15", "สูตรเสมอ"],
    "16-16-16": ["16-16-16", "161616", "16 16 16", "16.16.16", "สูตรเสมอ 16"],
    "13-13-21": ["13-13-21", "131321", "13 13 21", "13.13.21"],
    "20-8-20":  ["20-8-20", "20820", "20 8 20", "20.8.20"],
    "21-0-0":   ["21-0-0", "2100", "21 0 0", "21.0.0", "แอมโมเนียมซัลเฟต"],
    "0-46-0":   ["0-46-0", "0460", "0 46 0", "0.46.0", "tsp"],
    "14-14-21": ["14-14-21", "141421", "14 14 21", "14.14.21"],
    "20-10-12": ["20-10-12", "201012", "20 10 12", "20.10.12"],
    "12-12-17": ["12-12-17", "121217", "12 12 17", "12.12.17"],
    "20-20-0":  ["20-20-0", "20200", "20 20 0", "20.20.0"],
    "25-7-7":   ["25-7-7", "2577", "25 7 7", "25.7.7"],
}

_FALLBACK_CROPS: Dict[str, List[str]] = {
    # Crop names (canonical -> aliases/variants)
    "นาข้าว":       ["นาข้าว", "ข้าว", "ทำนา", "rice", "นา"],
    "ข้าวโพด":      ["ข้าวโพด", "โพด", "corn", "maize", "ข้าวโพดเลี้ยงสัตว์"],
    "อ้อย":         ["อ้อย", "sugarcane", "อ้อย", "ไร่อ้อย"],
    "มันสำปะหลัง":  ["มันสำปะหลัง", "มัน", "cassava", "มันสำปะหลัง", "ไร่มัน"],
    "ปาล์มน้ำมัน":  ["ปาล์มน้ำมัน", "ปาล์ม", "palm", "oil palm", "สวนปาล์ม"],
    "ยางพารา":      ["ยางพารา", "ยาง", "rubber", "สวนยาง", "ต้นยาง"],
}

# Combined fallback: all entries (formulas + crops)
_FALLBACK_PRODUCTS: Dict[str, List[str]] = {**_FALLBACK_FORMULAS, **_FALLBACK_CROPS}


class ProductRegistry:
    """
    Singleton registry of fertilizer formulas and crop names, loaded from DB at startup.

    Provides:
    - extract_product_name(question) -- exact + diacritics + formula-pattern + fuzzy match
    - fuzzy_match(text, threshold) -- fuzzy only
    - get_canonical_list() -- flat list of canonical names (crops + formulas)
    - get_aliases(name) -- aliases for a product/crop
    - is_known_product(name) -- check if name is canonical
    - get_product_names_dict() -- dict of canonical -> [aliases]
    """

    _instance: Optional['ProductRegistry'] = None

    def __init__(self):
        self._products: Dict[str, List[str]] = {}       # canonical -> [aliases]
        self._canonical_list: List[str] = []             # flat list for LLM prompt
        self._alias_index: Dict[str, str] = {}           # lowercase alias -> canonical
        self._stripped_index: Dict[str, str] = {}         # diacritics-stripped alias -> canonical
        self._loaded: bool = False
        self._load_time: float = 0
        # Separate tracking of crops and formulas for structured queries
        self._crops: List[str] = []
        self._formulas: List[str] = []

    @classmethod
    def get_instance(cls) -> 'ProductRegistry':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def loaded(self) -> bool:
        return self._loaded

    # =====================================================================
    # Loading
    # =====================================================================

    async def load_from_db(self, supabase_client) -> bool:
        """
        Load fertilizer formulas and crop names from mahbin_npk table.
        Auto-generates formula/crop variants for each entry.
        Falls back to _FALLBACK_PRODUCTS if DB is unavailable.
        """
        products: Dict[str, List[str]] = {}
        crops_set: set = set()
        formulas_set: set = set()
        try:
            if supabase_client is None:
                raise RuntimeError("supabase_client is None")

            result = supabase_client.table('mahbin_npk').select(
                'id, crop, growth_stage, fertilizer_formula'
            ).execute()
            if not result.data:
                raise RuntimeError("No data returned from mahbin_npk")

            logger.info(f"ProductRegistry: loaded {len(result.data)} rows from mahbin_npk")

            # Collect unique crops and formulas
            for row in result.data:
                crop = row.get('crop', '').strip()
                formula = row.get('fertilizer_formula', '').strip()
                if crop:
                    crops_set.add(crop)
                if formula:
                    formulas_set.add(formula)

            # Register each crop with its variants
            for crop in sorted(crops_set):
                auto_variants = _generate_crop_variants(crop)
                # Merge with fallback hand-crafted aliases if available
                fallback_aliases = _FALLBACK_CROPS.get(crop, [])
                all_aliases = sorted(set(auto_variants + [a.lower() for a in fallback_aliases]))
                products[crop] = all_aliases

            # Register each fertilizer formula with its variants
            for formula in sorted(formulas_set):
                auto_variants = _generate_formula_variants(formula)
                # Merge with fallback aliases if available
                fallback_aliases = _FALLBACK_FORMULAS.get(formula, [])
                all_aliases = sorted(set(auto_variants + [a.lower() for a in fallback_aliases]))
                products[formula] = all_aliases

            # Also include fallback-only entries not found in DB
            for name, aliases in _FALLBACK_PRODUCTS.items():
                if name not in products:
                    if _FORMULA_PATTERN.match(name):
                        auto_variants = _generate_formula_variants(name)
                    else:
                        auto_variants = _generate_crop_variants(name)
                    all_aliases = sorted(set(auto_variants + [a.lower() for a in aliases]))
                    products[name] = all_aliases
                    logger.debug(f"  fallback-only entry: {name}")

        except Exception as e:
            logger.warning(f"ProductRegistry: DB load failed ({e}), using fallback data")
            for name, aliases in _FALLBACK_PRODUCTS.items():
                if _FORMULA_PATTERN.match(name):
                    auto_variants = _generate_formula_variants(name)
                else:
                    auto_variants = _generate_crop_variants(name)
                all_aliases = sorted(set(auto_variants + [a.lower() for a in aliases]))
                products[name] = all_aliases
            crops_set = set(_FALLBACK_CROPS.keys())
            formulas_set = set(_FALLBACK_FORMULAS.keys())

        self._crops = sorted(crops_set)
        self._formulas = sorted(formulas_set)
        self._build_index(products)
        return self._loaded

    def load_from_dict(self, products_dict: Dict[str, List[str]]) -> None:
        """Load from a dict directly (for testing or fallback)."""
        products: Dict[str, List[str]] = {}
        crops_set: set = set()
        formulas_set: set = set()
        for name, aliases in products_dict.items():
            if _FORMULA_PATTERN.match(name):
                auto_variants = _generate_formula_variants(name)
                formulas_set.add(name)
            else:
                auto_variants = _generate_crop_variants(name)
                crops_set.add(name)
            all_aliases = sorted(set(auto_variants + [a.lower() for a in aliases]))
            products[name] = all_aliases
        self._crops = sorted(crops_set)
        self._formulas = sorted(formulas_set)
        self._build_index(products)

    def _build_index(self, products: Dict[str, List[str]]) -> None:
        """Build reverse-lookup indexes from products dict."""
        self._products = products
        self._canonical_list = sorted(products.keys())

        # Build alias -> canonical index (longest aliases first for greedy match)
        alias_index: Dict[str, str] = {}
        stripped_index: Dict[str, str] = {}
        for canonical, aliases in products.items():
            canonical_lower = canonical.lower()
            # Canonical name itself is an alias
            alias_index[canonical_lower] = canonical
            stripped_index[_strip_diacritics(canonical_lower)] = canonical
            for alias in aliases:
                alias_lower = alias.lower()
                alias_index[alias_lower] = canonical
                stripped = _strip_diacritics(alias_lower)
                stripped_index[stripped] = canonical

        self._alias_index = alias_index
        self._stripped_index = stripped_index
        self._loaded = True
        self._load_time = time.time()
        logger.info(
            f"ProductRegistry: indexed {len(self._canonical_list)} entries "
            f"({len(self._crops)} crops, {len(self._formulas)} formulas), "
            f"{len(alias_index)} aliases"
        )

    # =====================================================================
    # Matching
    # =====================================================================

    def _extract_formula_from_text(self, text: str) -> Optional[str]:
        """
        Try to extract an N-P-K formula pattern from text and match it
        to a known canonical formula.

        Handles formats like: 46-0-0, 46 0 0, 46.0.0
        """
        # Normalize separators: dots and spaces to dashes for matching
        normalized = text
        # Match various separator patterns: "46-0-0", "46 0 0", "46.0.0"
        pattern_variants = re.findall(
            r'(\d{1,2})\s*[-\.\u2013]\s*(\d{1,2})\s*[-\.\u2013]\s*(\d{1,2})',
            normalized
        )
        for n, p, k in pattern_variants:
            canonical_form = f"{int(n)}-{int(p)}-{int(k)}"
            if canonical_form in self._products:
                return canonical_form
        return None

    def extract_product_name(self, question: str) -> Optional[str]:
        """
        Extract fertilizer formula or crop name from user question.
        Pipeline: formula-pattern -> exact substring -> diacritics-stripped -> fuzzy match.
        """
        self._ensure_loaded()
        question_lower = question.lower()

        # Step 1: Try to extract NPK formula pattern directly (e.g. "46-0-0", "16 20 0")
        formula_match = self._extract_formula_from_text(question_lower)
        if formula_match:
            return formula_match

        # Step 2: Exact substring match -- scan aliases sorted by length (longest first)
        # to prefer more specific matches
        sorted_aliases = sorted(self._alias_index.keys(), key=len, reverse=True)
        for alias in sorted_aliases:
            if len(alias) < 2:
                continue
            if alias in question_lower:
                return self._alias_index[alias]

        # Step 3: Diacritics-stripped match
        question_stripped = _strip_diacritics(question_lower)
        sorted_stripped = sorted(self._stripped_index.keys(), key=len, reverse=True)
        for stripped_alias in sorted_stripped:
            if len(stripped_alias) < 2:
                continue
            if stripped_alias in question_stripped:
                return self._stripped_index[stripped_alias]

        # Step 4: Fuzzy match (fallback)
        return self.fuzzy_match(question)

    def fuzzy_match(self, text: str, threshold: float = 0.65) -> Optional[str]:
        """
        Fuzzy matching for misspelled crop names or formula references.
        e.g. "นาข่าว" -> "นาข้าว", "ข้าวโพท" -> "ข้าวโพด"
        """
        self._ensure_loaded()
        tokens = re.findall(r'[\u0E00-\u0E7F]+|[a-zA-Z]+|\d+[-\.\s]?\d+[-\.\s]?\d+', text)

        best_match = None
        best_score = 0.0

        for token in tokens:
            if len(token) < 2:
                continue
            token_lower = token.lower()
            for alias, canonical in self._alias_index.items():
                if len(alias) < 2:
                    continue
                # Direct comparison
                score = SequenceMatcher(None, token_lower, alias).ratio()
                if score > best_score and score >= threshold:
                    best_score = score
                    best_match = canonical

                # Sliding window for long tokens
                alias_len = len(alias)
                if len(token_lower) > alias_len + 1 and alias_len >= 2:
                    for i in range(len(token_lower) - alias_len + 2):
                        end = min(i + alias_len + 1, len(token_lower))
                        sub = token_lower[i:end]
                        if len(sub) < alias_len:
                            continue
                        score = SequenceMatcher(None, sub, alias).ratio()
                        if score > best_score and score >= threshold:
                            best_score = score
                            best_match = canonical

        return best_match

    # =====================================================================
    # Query API (backward-compatible)
    # =====================================================================

    def get_canonical_list(self) -> List[str]:
        """Flat sorted list of canonical names -- crops + formulas (for LLM prompt)."""
        self._ensure_loaded()
        return list(self._canonical_list)

    def get_crops(self) -> List[str]:
        """Get sorted list of crop names."""
        self._ensure_loaded()
        return list(self._crops)

    def get_formulas(self) -> List[str]:
        """Get sorted list of fertilizer formulas."""
        self._ensure_loaded()
        return list(self._formulas)

    def get_aliases(self, name: str) -> List[str]:
        """Get aliases for a canonical product/crop/formula name."""
        self._ensure_loaded()
        return list(self._products.get(name, [name.lower()]))

    def is_known_product(self, name: str) -> bool:
        """Check if name is a known canonical entry (crop or formula)."""
        self._ensure_loaded()
        return name in self._products

    def get_product_names_dict(self) -> Dict[str, List[str]]:
        """Get full products dict {canonical: [aliases]}."""
        self._ensure_loaded()
        return dict(self._products)

    def resolve_alias(self, alias: str) -> Optional[str]:
        """Resolve an alias to canonical name, or None."""
        self._ensure_loaded()
        return self._alias_index.get(alias.lower())

    # =====================================================================
    # Internal
    # =====================================================================

    def _ensure_loaded(self) -> None:
        """Ensure the registry is loaded. If not, load from fallback."""
        if not self._loaded:
            logger.warning("ProductRegistry: not loaded yet, using fallback data")
            self.load_from_dict(_FALLBACK_PRODUCTS)
