"""Claude-Code-style spinner verbs.

The verb pool and the ``<Verb>… (<elapsed> · ↓ <tokens> · thinking)`` shape
were taken from Claude Code 2.1.274 (see the display-layer research notes).
Fulilian keeps its own spinner contract: the word replaces the fixed
``Thinking`` label only, and the elapsed/token metrics are unchanged.

``display.spinner_verbs`` in config.yaml selects the behaviour:
``cc`` (default) uses the pool, ``off`` restores the fixed ``Thinking`` label.
"""

import hashlib

# Extracted verbatim from Claude Code 2.1.274's status-verb pool.
SPINNER_VERBS: tuple[str, ...] = (
    "Accomplishing", "Actioning", "Actualizing", "Architecting", "Baking", "Beaming",
    "Beboppin'", "Befuddling", "Billowing", "Blanching", "Bloviating", "Boogieing",
    "Boondoggling", "Booping", "Bootstrapping", "Brewing", "Bunning", "Burrowing",
    "Calculating", "Canoodling", "Caramelizing", "Cascading", "Catapulting", "Cerebrating",
    "Channeling", "Channelling", "Choreographing", "Churning", "Clauding", "Coalescing",
    "Cogitating", "Combobulating", "Composing", "Computing", "Concocting", "Considering",
    "Contemplating", "Cooking", "Crafting", "Creating", "Crunching", "Crystallizing",
    "Cultivating", "Deciphering", "Deliberating", "Determining", "Dilly-dallying", "Discombobulating",
    "Doing", "Doodling", "Drizzling", "Ebbing", "Effecting", "Elucidating",
    "Embellishing", "Enchanting", "Envisioning", "Fermenting", "Fiddle-faddling", "Finagling",
    "Flambéing", "Flibbertigibbeting", "Flowing", "Flummoxing", "Fluttering", "Forging",
    "Forming", "Frolicking", "Frosting", "Gallivanting", "Galloping", "Garnishing",
    "Generating", "Gesticulating", "Germinating", "Gitifying", "Grooving", "Gusting",
    "Harmonizing", "Hashing", "Hatching", "Herding", "Honking", "Hullaballooing",
    "Hyperspacing", "Ideating", "Imagining", "Improvising", "Incubating", "Inferring",
    "Infusing", "Ionizing", "Jitterbugging", "Julienning", "Kerfuffling", "Kneading",
    "Leavening", "Levitating", "Lollygagging", "Manifesting", "Marinating", "Meandering",
    "Metamorphosing", "Misting", "Moonwalking", "Moseying", "Mulling", "Mustering",
    "Musing", "Nebulizing", "Nesting", "Newspapering", "Noodling", "Nucleating",
    "Orbiting", "Orchestrating", "Osmosing", "Perambulating", "Percolating", "Perusing",
    "Philosophising", "Photosynthesizing", "Pollinating", "Pondering", "Pontificating", "Pouncing",
    "Precipitating", "Prestidigitating", "Processing", "Proofing", "Propagating", "Puttering",
    "Puzzling", "Quantumizing", "Razzle-dazzling", "Razzmatazzing", "Recombobulating", "Reticulating",
    "Roosting", "Ruminating", "Sautéing", "Scampering", "Schlepping", "Scurrying",
    "Seasoning", "Shenaniganing", "Shimmying", "Simmering", "Skedaddling", "Sketching",
    "Slithering", "Smooshing", "Sock-hopping", "Spelunking", "Spinning", "Sprouting",
    "Stewing", "Sublimating", "Swirling", "Swooping", "Symbioting", "Synthesizing",
    "Tempering", "Thinking", "Thundering", "Tinkering", "Tomfoolering", "Topsy-turvying",
    "Transfiguring", "Transmogrifying", "Transmuting", "Twisting", "Undulating", "Unfurling",
    "Unravelling", "Vibing", "Waddling", "Wandering", "Warping", "Whatchamacalliting",
    "Whirlpooling", "Whirring", "Whisking", "Wibbling", "Working", "Wrangling",
    "Zesting", "Zigzagging",
)

DEFAULT_VERB = "Thinking"


def pick_verb(seed: str) -> str:
    """Deterministically pick a verb for *seed*.

    Determinism matters: the spinner repaints several times per second, so a
    random pick per frame would flicker.  Callers seed with the phase name
    plus a value fixed for that phase instance, giving one stable verb per
    phase and a fresh one when the phase changes.
    """
    if not seed:
        return DEFAULT_VERB
    digest = hashlib.blake2s(str(seed).encode("utf-8"), digest_size=4).digest()
    return SPINNER_VERBS[int.from_bytes(digest, "big") % len(SPINNER_VERBS)]
