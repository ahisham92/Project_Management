"""What a new library starts with: the questions, the words, the standards.

All of it is a starting point for the administrator to change, not a source
of truth. The equivalents are the usual counterparts in concrete, steel and
marine work; the withdrawn list is standards the office's own sections have
been found citing after they were replaced. Check both against the current
catalogues before relying on them for a contract.
"""

from __future__ import annotations

# key, question, choices, default, group, kind ("one" or "many")
OPTIONS: list[tuple[str, str, str, str, str, str]] = [
    ("standards", "Standards the specification is written to", "BS EN|ACI/ASTM|Both", "BS EN",
     "Basis", "one"),
    ("english", "English", "UK|UK with -ize|US", "UK", "Basis", "one"),
    ("stage", "Design stage", "Concept|Preliminary|Final Design|Tender|Issued for Construction",
     "Final Design", "Basis", "one"),
    ("contract", "Form of contract", "FIDIC Red Book|FIDIC Yellow Book|FIDIC Silver Book|Other",
     "FIDIC Red Book", "Basis", "one"),
    ("design_life", "Design life", "50 years|100 years", "50 years", "Basis", "one"),
    ("seismic", "Seismic detailing", "No|Yes", "No", "Basis", "one"),
    ("leed", "LEED certification", "None|v4|v4.1", "None", "Sustainability and compliance", "one"),
    ("conformity", "Certificates of conformity", "None|SASO SABER|Other national scheme", "None",
     "Sustainability and compliance", "one"),
    ("structures", "What the project builds", "Buildings|Marine structures|Bridges", "Buildings",
     "Scope", "many"),
    ("elements", "Structural elements",
     "Piles|Pile caps|Foundations|Slab on grade|Columns|Beams|Suspended slabs and floors|Walls|"
     "Basement walls|Retaining walls|Precast|Deck|Quay walls|Blinding|Topping|"
     "Water-retaining structures", "", "Elements", "many"),
    ("cranes", "Crane rails and cranes", "No|Yes", "No", "Scope", "one"),
    ("demolition", "Demolition of existing structures", "No|Yes", "No", "Scope", "one"),
    ("shoring", "Shoring and facade retention", "No|Yes", "No", "Scope", "one"),
    ("monitoring", "Structural monitoring", "No|Yes", "No", "Scope", "one"),
    ("exposure", "Exposure", "General|Marine|Aggressive ground", "General", "Environment", "one"),
    ("climate", "Climate at placing", "Hot|Temperate|Cold", "Hot", "Environment", "one"),
    ("cement", "Cementitious system", "CEM I|CEM I + GGBS|CEM I + fly ash|CEM I + silica fume|CEM III",
     "CEM I + GGBS", "Concrete", "many"),
    ("cast_in_place", "Cast-in-place concrete", "No|Yes", "Yes", "Concrete", "one"),
    ("mass_concrete", "Mass concrete pours", "No|Yes", "No", "Concrete", "one"),
    ("water_retaining", "Water-retaining structures", "No|Yes", "No", "Concrete", "one"),
    ("underwater", "Underwater or tremie concrete", "No|Yes", "No", "Concrete", "one"),
    ("self_compacting", "Self-compacting concrete", "No|Yes", "No", "Concrete", "one"),
    ("fibres", "Fibre-reinforced concrete", "No|Yes", "No", "Concrete", "one"),
    ("precast", "Precast concrete", "None|Plant precast|Precast prestressed", "None", "Concrete", "many"),
    ("post_tensioning", "Post-tensioning", "None|Unbonded|Bonded", "None", "Concrete", "many"),
    ("tilt_up", "Tilt-up concrete panels", "No|Yes", "No", "Concrete", "one"),
    ("shotcrete", "Shotcrete (sprayed concrete)", "No|Yes", "No", "Concrete", "one"),
    ("repair", "Repair and maintenance of existing concrete", "No|Yes", "No", "Concrete", "one"),
    ("testing", "Compressive strength specimens", "Cubes|Cylinders", "Cubes", "Concrete", "one"),
    ("finish", "Exposed formed finishes", "Standard|Architectural", "Standard", "Concrete", "one"),
    ("rebar", "Reinforcement", "Uncoated|Galvanized|Epoxy-coated|Stainless steel|GFRP bars",
     "Uncoated", "Reinforcement", "many"),
    ("couplers", "Mechanical couplers", "No|Yes", "Yes", "Reinforcement", "one"),
    ("anchors", "Post-installed anchors", "No|Yes", "No", "Reinforcement", "one"),
    ("cathodic", "Cathodic protection", "None|Continuity provisions only|Installed", "None",
     "Reinforcement", "one"),
    ("steel_framing", "Structural steel framing", "No|Yes", "Yes", "Steel", "one"),
    ("steel_systems", "Other steelwork",
     "None|Steel joists|Steel deck|Cold-formed framing|Space frames|Isolated members", "None",
     "Steel", "many"),
    ("stairs", "Metal stairs", "None|Metal pan|Floor plate|Grating", "None", "Steel", "many"),
    ("steel_protection", "Structural steel protection",
     "Hot-dip galvanized|Paint system|Galvanized and painted", "Hot-dip galvanized", "Steel", "one"),
    ("fire", "Fire protection of steel", "None|Intumescent|Cementitious", "None", "Steel", "one"),
    ("aess", "Architecturally exposed structural steel", "No|Yes", "No", "Steel", "one"),
    ("fenders", "Fender type", "None|Cone|Cell|Arch|Pneumatic", "Cone", "Marine furniture", "one"),
    ("bollards", "Bollard capacity", "None|50 t|100 t|150 t|200 t", "150 t", "Marine furniture", "one"),
    ("ladders", "Ladders and mooring rings", "No|Yes", "Yes", "Marine furniture", "one"),
    ("floating_piers", "Floating piers and pontoons", "No|Yes", "No", "Marine furniture", "one"),
    ("bridge_items", "Bridge items",
     "None|Prestressed girders|Bearings|Expansion joints|Parapets and railings|Drainage|"
     "Deck waterproofing", "None", "Bridges", "many"),
    ("waterproofing", "Waterproofing",
     "None|Bituminous sheet|Liquid membrane|Crystalline|Bituminous dampproofing|"
     "Self-adhering sheet|APP modified sheet|SBS modified sheet|Elastomeric sheet|"
     "Thermoplastic sheet|Crystalline admixture|Acrylic-modified cement|Bentonite",
     "None", "Protection", "many"),
]

# The project's elements, drawn as tiles to tick rather than asked as
# questions: the question, how its tile works, and the drawing on it. A
# "toggle" tile is the question's second answer when ticked and its first
# when not; a "pick" tile carries the question's answers in a list; a
# question that takes several answers has a tile for each (bar None).
# Drawings are named in templates/specs/_icons.html; an answer with no
# drawing of its own takes its question's.
ELEMENT_GROUPS: list[tuple[str, str]] = [
    ("elements", "Structural elements"),
    ("builds", "What the project builds"),
    ("concrete", "Concrete"),
    ("reinforcement", "Reinforcement and fixings"),
    ("steel", "Steel"),
    ("bridges", "Bridges"),
    ("marine", "Marine"),
    ("waterproofing", "Waterproofing"),
    ("works", "Other works"),
]
# key, tile group, "toggle" / "pick" / "many", drawing
ELEMENTS: list[tuple[str, str, str, str]] = [
    ("elements", "elements", "many", "element"),
    ("structures", "builds", "many", "building"),
    ("cast_in_place", "concrete", "toggle", "cast_in_place"),
    ("precast", "concrete", "many", "precast"),
    ("post_tensioning", "concrete", "many", "post_tensioning"),
    ("mass_concrete", "concrete", "toggle", "mass_concrete"),
    ("tilt_up", "concrete", "toggle", "tilt_up"),
    ("shotcrete", "concrete", "toggle", "shotcrete"),
    ("finish", "concrete", "toggle", "architectural"),
    ("water_retaining", "concrete", "toggle", "water_retaining"),
    ("underwater", "concrete", "toggle", "tremie"),
    ("self_compacting", "concrete", "toggle", "self_compacting"),
    ("fibres", "concrete", "toggle", "fibres"),
    ("repair", "concrete", "toggle", "repair"),
    ("rebar", "reinforcement", "many", "rebar"),
    ("couplers", "reinforcement", "toggle", "couplers"),
    ("anchors", "reinforcement", "toggle", "anchors"),
    ("steel_framing", "steel", "toggle", "steel_frame"),
    ("steel_systems", "steel", "many", "steel_joists"),
    ("stairs", "steel", "many", "stair_pan"),
    ("aess", "steel", "toggle", "aess"),
    ("cranes", "steel", "toggle", "crane"),
    ("bridge_items", "bridges", "many", "bridge"),
    ("fenders", "marine", "pick", "fender"),
    ("bollards", "marine", "pick", "bollard"),
    ("ladders", "marine", "toggle", "mooring"),
    ("floating_piers", "marine", "toggle", "floating_pier"),
    ("waterproofing", "waterproofing", "many", "membrane"),
    ("demolition", "works", "toggle", "demolition"),
    ("shoring", "works", "toggle", "shoring"),
    ("monitoring", "works", "toggle", "monitoring"),
]
# (key, answer): what its tile says, where the answer alone would not do
ELEMENT_LABELS: dict[tuple[str, str], str] = {
    ("precast", "Plant precast"): "Precast concrete",
    ("post_tensioning", "Unbonded"): "Post-tensioned, unbonded",
    ("post_tensioning", "Bonded"): "Post-tensioned, bonded",
    ("finish", "Architectural"): "Architectural concrete",
    ("rebar", "Uncoated"): "Plain bars",
    ("rebar", "Galvanized"): "Galvanized bars",
    ("rebar", "Epoxy-coated"): "Epoxy-coated bars",
    ("rebar", "Stainless steel"): "Stainless steel bars",
    ("stairs", "Metal pan"): "Metal pan stairs",
    ("stairs", "Floor plate"): "Floor plate stairs",
    ("stairs", "Grating"): "Grating stairs",
    ("steel_systems", "Isolated members"): "Lintels and isolated members",
    ("waterproofing", "Bituminous sheet"): "Bituminous sheet (general)",
    ("waterproofing", "Liquid membrane"): "Liquid-applied membrane",
}
# (key, answer): its own drawing
ELEMENT_ICONS: dict[tuple[str, str], str] = {
    ("structures", "Buildings"): "building",
    ("structures", "Marine structures"): "marine",
    ("structures", "Bridges"): "bridge",
    ("precast", "Plant precast"): "precast",
    ("precast", "Precast prestressed"): "precast_prestressed",
    ("post_tensioning", "Unbonded"): "pt_unbonded",
    ("post_tensioning", "Bonded"): "pt_bonded",
    ("rebar", "Uncoated"): "rebar",
    ("rebar", "Galvanized"): "rebar_galvanized",
    ("rebar", "Epoxy-coated"): "rebar_epoxy",
    ("rebar", "Stainless steel"): "rebar_stainless",
    ("rebar", "GFRP bars"): "gfrp",
    ("steel_systems", "Steel joists"): "steel_joists",
    ("steel_systems", "Steel deck"): "steel_deck",
    ("steel_systems", "Cold-formed framing"): "cold_formed",
    ("steel_systems", "Space frames"): "space_frame",
    ("steel_systems", "Isolated members"): "isolated_members",
    ("stairs", "Metal pan"): "stair_pan",
    ("stairs", "Floor plate"): "stair_plate",
    ("stairs", "Grating"): "stair_grating",
    ("bridge_items", "Prestressed girders"): "girders",
    ("bridge_items", "Bearings"): "bearing",
    ("bridge_items", "Expansion joints"): "expansion_joint",
    ("bridge_items", "Parapets and railings"): "parapet",
    ("bridge_items", "Drainage"): "bridge_drainage",
    ("bridge_items", "Deck waterproofing"): "deck_waterproofing",
    ("waterproofing", "Bituminous sheet"): "membrane",
    ("waterproofing", "Liquid membrane"): "liquid_membrane",
    ("waterproofing", "Crystalline"): "crystalline",
    ("waterproofing", "Bituminous dampproofing"): "dampproofing",
    ("waterproofing", "Self-adhering sheet"): "membrane",
    ("waterproofing", "APP modified sheet"): "torch_sheet",
    ("waterproofing", "SBS modified sheet"): "torch_sheet",
    ("waterproofing", "Elastomeric sheet"): "membrane",
    ("waterproofing", "Thermoplastic sheet"): "membrane",
    ("waterproofing", "Crystalline admixture"): "admixture",
    ("waterproofing", "Acrylic-modified cement"): "cementitious",
    ("waterproofing", "Bentonite"): "bentonite",
}

# The structural elements a project can say it has (the "elements" question):
# slug, label, and the kinds of work it usually belongs to ("|"-joined answers
# of "structures"). The slug is how the text names an element, in
# {{key@slug|...}}, so it never changes once a library uses it; the label is
# the answer stored. A project can add its own elements by name as well.
ELEMENT_KINDS: list[tuple[str, str, str]] = [
    ("piles", "Piles", "Buildings|Marine structures|Bridges"),
    ("pile_caps", "Pile caps", "Buildings|Marine structures|Bridges"),
    ("foundations", "Foundations", "Buildings|Bridges"),
    ("slab_on_grade", "Slab on grade", "Buildings|Marine structures"),
    ("columns", "Columns", "Buildings|Bridges"),
    ("beams", "Beams", "Buildings|Marine structures|Bridges"),
    ("slabs", "Suspended slabs and floors", "Buildings"),
    ("walls", "Walls", "Buildings"),
    ("basement_walls", "Basement walls", "Buildings"),
    ("retaining_walls", "Retaining walls", "Buildings|Bridges"),
    ("precast", "Precast", "Buildings|Marine structures|Bridges"),
    ("deck", "Deck", "Marine structures|Bridges"),
    ("quay_walls", "Quay walls", "Marine structures"),
    ("blinding", "Blinding", "Buildings|Marine structures|Bridges"),
    ("topping", "Topping", "Buildings"),
    ("water_retaining", "Water-retaining structures", "Buildings"),
]
ELEMENT_ICONS.update({("elements", label): "el_" + slug for slug, label, _for in ELEMENT_KINDS})


def element_slug(label: str) -> str:
    """The slug of an element, by its label: the listed one for a listed
    element (whatever its case), otherwise the label itself in lower case with
    everything but letters and digits made "_"."""
    wanted = " ".join((label or "").split()).lower()
    for slug, known, _for in ELEMENT_KINDS:
        if known.lower() == wanted or slug == wanted:
            return slug
    return "_".join(part for part in "".join(c if c.isalnum() else " " for c in wanted).split())

# The kinds of specification the office keeps, each its own set of sections:
# code, name, what it is for.
FAMILIES: list[tuple[str, str, str]] = [
    ("03A", "British Standards",
     "NBS-style sections to BS EN, for projects specified the British way."),
    ("15A", "American",
     "MasterFormat sections to ACI and ASTM. Marine works are issued under this one too."),
    ("16A", "Saudi Arabia",
     "MasterFormat sections to the Saudi Building Code (SBC) and SASO."),
]
# How a new project of each kind starts answering the basis questions.
FAMILY_DEFAULTS: dict[str, dict[str, str]] = {
    "03A": {"standards": "BS EN", "english": "UK"},
    "15A": {"standards": "ACI/ASTM", "english": "US"},
    "16A": {"standards": "ACI/ASTM", "english": "US", "conformity": "SASO SABER"},
}

# key, what it is, default
VARIABLES: list[tuple[str, str, str]] = [
    ("engineer", "The Engineer, as the contract names it", "Engineer"),
    ("employer", "The Employer, as the contract names it", "Employer"),
    ("contractor", "The Contractor, as the contract names it", "Contractor"),
    ("authority", "The authority having jurisdiction", ""),
    ("country", "The country the works are in", ""),
    ("site", "The site, as the specification names it", ""),
    ("concrete_class", "Structural concrete strength class", "C40/50"),
    ("exposure_class", "Exposure class of the marine concrete", "XS3"),
    ("cover", "Nominal cover to reinforcement", "75 mm"),
    ("max_aggregate", "Maximum aggregate size", "20 mm"),
    ("steel_grade", "Structural steel grade", "S355"),
    ("rebar_grade", "Reinforcement grade", "B500B"),
    ("galvanizing", "Minimum galvanizing thickness", "85 µm"),
]

# topic, BS / EN / ISO, ASTM / ACI (several separated by ;)
EQUIVALENTS: list[tuple[str, str, str]] = [
    # Concrete materials
    ("Cement", "BS EN 197-1", "ASTM C150; ASTM C595; ASTM C1157"),
    ("Fly ash", "BS EN 450-1", "ASTM C618"),
    ("Ground granulated blast-furnace slag", "BS EN 15167-1", "ASTM C989"),
    ("Silica fume", "BS EN 13263-1", "ASTM C1240"),
    ("Aggregates", "BS EN 12620", "ASTM C33"),
    ("Lightweight aggregates", "BS EN 13055", "ASTM C330"),
    ("Aggregates for mortar", "BS EN 13139", "ASTM C144"),
    ("Admixtures", "BS EN 934-2", "ASTM C494; ASTM C260; ASTM C1017"),
    ("Mixing water", "BS EN 1008", "ASTM C1602; AASHTO T26"),
    ("Fibres for concrete", "BS EN 14889-1", "ASTM C1116"),
    # Concrete production and execution
    ("Concrete production", "BS EN 206", "ASTM C94; ASTM C685"),
    ("Durability and mix limits", "BS 8500-1", "ACI 201.2R"),
    ("Concrete mix proportioning", "BS 8500-1", "ACI 211.1"),
    ("Self-compacting concrete", "BS EN 206", "ACI 237R"),
    ("Execution of concrete structures", "BS EN 13670", "ACI 301"),
    ("Tolerances", "BS EN 13670", "ACI 117"),
    ("Placing concrete", "BS EN 13670", "ACI 304R; ACI 304"),
    ("Hot weather concreting", "BS EN 13670", "ACI 305R; ACI 305.1; ACI 305"),
    ("Cold weather concreting", "BS EN 13670", "ACI 306R; ACI 306.1; ACI 306"),
    ("Consolidation", "BS EN 13670", "ACI 309R; ACI 309"),
    ("Formwork", "BS EN 13670", "ACI 347R; ACI 347"),
    ("Mass concrete", "BS EN 13670", "ACI 207.1R"),
    ("Concrete floors", "BS 8204-2", "ACI 302.1R"),
    ("Design of concrete structures", "BS EN 1992-1-1", "ACI 318"),
    ("Liquid-retaining structures", "BS EN 1992-3", "ACI 350"),
    ("Actions on structures", "BS EN 1991-1-1", "ASCE 7"),
    ("Wind actions", "BS EN 1991-1-4", "ASCE 7"),
    ("Seismic design", "BS EN 1998-1", "ASCE 7"),
    ("Marine concrete", "BS 6349-1-4", "ACI 357R; ACI 357"),
    ("Precast concrete", "BS EN 13369", "PCI MNL-116"),
    ("Testing laboratories", "BS EN ISO/IEC 17025", "ASTM C1077; ASTM E329"),
    # Tests on aggregates and cement
    ("Sieve analysis", "BS EN 933-1", "ASTM C136; ASTM C117"),
    ("Particle density and water absorption", "BS EN 1097-6", "ASTM C127; ASTM C128"),
    ("Resistance to fragmentation", "BS EN 1097-2", "ASTM C131; ASTM C535"),
    ("Soundness (magnesium sulfate)", "BS EN 1367-2", "ASTM C88"),
    ("Chemical tests on aggregates", "BS EN 1744-1", "ASTM C40; ASTM C123"),
    ("Mortar strength of cement", "BS EN 196-1", "ASTM C109"),
    ("Chemical analysis of cement", "BS EN 196-2", "ASTM C114"),
    ("Setting time of cement", "BS EN 196-3", "ASTM C191"),
    ("Fineness of cement", "BS EN 196-6", "ASTM C204"),
    # Tests on concrete
    ("Sampling fresh concrete", "BS EN 12350-1", "ASTM C172"),
    ("Slump", "BS EN 12350-2", "ASTM C143"),
    ("Density of fresh concrete", "BS EN 12350-6", "ASTM C138"),
    ("Air content", "BS EN 12350-7", "ASTM C231; ASTM C173"),
    ("Slump-flow", "BS EN 12350-8", "ASTM C1611"),
    ("Segregation resistance", "BS EN 12350-11", "ASTM C1610"),
    ("J-ring", "BS EN 12350-12", "ASTM C1621"),
    ("Making and curing specimens", "BS EN 12390-2", "ASTM C31; ASTM C192"),
    ("Compressive strength", "BS EN 12390-3", "ASTM C39"),
    ("Flexural strength", "BS EN 12390-5", "ASTM C78"),
    ("Tensile splitting strength", "BS EN 12390-6", "ASTM C496"),
    ("Density of hardened concrete", "BS EN 12390-7", "ASTM C642"),
    ("Cores", "BS EN 12504-1", "ASTM C42"),
    ("Rebound hammer", "BS EN 12504-2", "ASTM C805"),
    ("Ultrasonic pulse velocity", "BS EN 12504-4", "ASTM C597"),
    ("Chloride content of concrete", "BS EN 14629", "ASTM C1218; ASTM C1152"),
    # Reinforcement
    ("Reinforcing bars", "BS 4449", "ASTM A615"),
    ("Weldable reinforcing bars", "BS 4449", "ASTM A706"),
    ("Welded fabric", "BS 4483", "ASTM A1064; ASTM A185; ASTM A497"),
    ("Stainless steel reinforcement", "BS 6744", "ASTM A955; ASTM A1022"),
    ("Galvanized reinforcement", "BS EN ISO 14657", "ASTM A767"),
    ("Epoxy-coated reinforcement", "BS EN ISO 14654", "ASTM A775; ASTM A934"),
    ("Mechanical splices", "BS ISO 15835-1", "ASTM A1034"),
    ("Welding of reinforcement", "BS EN ISO 17660-1", "AWS D1.4"),
    ("Detailing and bending of reinforcement", "BS 8666", "ACI 315; ACI SP-066"),
    # Structural steel
    ("Structural steel: general delivery conditions", "BS EN 10025-1", "ASTM A6"),
    ("Structural steel", "BS EN 10025-2", "ASTM A572; ASTM A992; ASTM A36"),
    ("Hollow sections", "BS EN 10210-1", "ASTM A500"),
    ("Steel pipe", "BS EN 10255", "ASTM A53"),
    ("Cold-finished bars", "BS EN 10277", "ASTM A108"),
    ("Stainless steel plate and sheet", "BS EN 10088-2", "ASTM A240"),
    ("Stainless steel bars", "BS EN 10088-3", "ASTM A276"),
    ("Ultrasonic testing of plate", "BS EN 10160", "ASTM A435"),
    ("Steel castings", "BS EN 10293", "ASTM A27; ASTM A148"),
    ("Steel castings for pressure", "BS EN 10213", "ASTM A216"),
    ("Steel forgings", "BS EN 10250-2", "ASTM A668"),
    ("Ductile iron castings", "BS EN 1563", "ASTM A536"),
    ("Mechanical testing of steel", "BS EN ISO 6892-1", "ASTM A370"),
    ("Charpy impact test", "BS EN ISO 148-1", "ASTM E23"),
    ("Structural bolting assemblies", "BS EN 14399", "ASTM F3125; ASTM A325; ASTM A490"),
    ("Nuts", "BS EN ISO 898-2", "ASTM A563"),
    ("Washers", "BS EN 14399-6", "ASTM F436"),
    ("Ordinary bolts", "BS EN ISO 4014", "ASTM A307"),
    ("Headed studs", "BS EN ISO 13918", "ASTM A108"),
    ("Steel structures: execution", "BS EN 1090-2", "AISC 303"),
    ("Structural welding", "BS EN 1090-2", "AWS D1.1"),
    ("Design of steel structures", "BS EN 1993-1-1", "AISC 360"),
    ("Composite structures", "BS EN 1994-1-1", "AISC 360"),
    ("Radiographic testing of welds", "BS EN ISO 17636-1", "ASTM E94"),
    ("Ultrasonic testing of welds", "BS EN ISO 17640", "ASTM E164"),
    ("Magnetic particle testing", "BS EN ISO 17638", "ASTM E709"),
    ("Penetrant testing", "BS EN ISO 3452-1", "ASTM E165"),
    # Coatings
    ("Hot-dip galvanizing", "BS EN ISO 1461", "ASTM A123; ASTM A153"),
    ("Zinc repair", "BS EN ISO 1461", "ASTM A780"),
    ("Mechanically deposited zinc", "BS EN ISO 12683", "ASTM B695"),
    ("Pull-off adhesion", "BS EN ISO 4624", "ASTM D4541"),
    ("Blast-cleaned surface profile", "BS EN ISO 8503-1", "ASTM D4417"),
    ("Dry film thickness", "BS EN ISO 2808", "ASTM D7091"),
    # Elastomers (fenders)
    ("Rubber hardness", "BS ISO 48-4", "ASTM D2240"),
    ("Rubber tensile properties", "BS ISO 37", "ASTM D412"),
    ("Rubber tear strength", "BS ISO 34-1", "ASTM D624"),
    ("Rubber compression set", "BS ISO 815-1", "ASTM D395"),
    ("Rubber heat ageing", "BS ISO 188", "ASTM D573"),
    ("Rubber ozone resistance", "BS ISO 1431-1", "ASTM D1149"),
    ("Rubber abrasion resistance", "BS ISO 4649", "ASTM D5963"),
]

# the standard as cited (with an edition to mean "that edition or older"), what
# replaced it, a note
WITHDRAWN: list[tuple[str, str, str]] = [
    ("BS 8110", "BS EN 1992-1-1", "withdrawn 2010"),
    ("BS 5950", "BS EN 1993-1-1", "withdrawn 2010"),
    ("BS 8007", "BS EN 1992-3", "withdrawn 2010"),
    ("BS 5400", "BS EN 1992-2", "withdrawn 2010"),
    ("BS 4360", "BS EN 10025-2", "structural steel grades, replaced by the EN 10025 series"),
    ("BS 729", "BS EN ISO 1461", "hot-dip galvanizing"),
    ("BS 5493", "BS EN ISO 12944", "protective coating of steel; see also BS EN ISO 14713"),
    ("BS 3148", "BS EN 1008", "water for concrete"),
    ("BS 5328", "BS EN 206", "concrete; with BS 8500"),
    ("BS 882", "BS EN 12620", "aggregates"),
    ("BS 12", "BS EN 197-1", "cement"),
    ("BS 3892", "BS EN 450-1", "fly ash"),
    ("BS 6699", "BS EN 15167-1", "GGBS"),
    ("BS 5075", "BS EN 934-2", "admixtures"),
    ("BS 1881", "BS EN 12350 / BS EN 12390 / BS EN 12504", "most parts withdrawn; cite the part"),
    ("BS 812", "BS EN 933 / BS EN 1097", "most parts withdrawn; cite the part"),
    ("ASTM A325", "ASTM F3125", "withdrawn 2016, consolidated into F3125"),
    ("ASTM A490", "ASTM F3125", "withdrawn 2016, consolidated into F3125"),
    ("ASTM F1852", "ASTM F3125", "consolidated into F3125"),
    ("ASTM A497", "ASTM A1064", "welded wire reinforcement, consolidated into A1064"),
    ("ASTM A185", "ASTM A1064", "welded wire reinforcement, consolidated into A1064"),
    ("ASTM A82", "ASTM A1064", "steel wire, consolidated into A1064"),
    ("ISO 9002", "ISO 9001", "withdrawn 2000"),
    ("BS EN 10210-1:1994", "BS EN 10210-1", "superseded edition"),
    ("BS EN 10219-1:1997", "BS EN 10219-1", "superseded edition"),
    ("BS EN 10164:1993", "BS EN 10164", "superseded edition"),
    ("BS EN 14399:2002", "BS EN 14399", "superseded edition"),
]

# find, suggest instead, why, only when (a condition on the project's choices),
# unless the next word is one of these. Suggestions only: nothing is changed
# until somebody accepts it.
WORDING: list[tuple[str, str, str, str, str]] = [
    ("building", "structure", "the project has no buildings", "structures!=Buildings",
     "product,products,code,codes,regulations,authority,and,construction,structural,information"),
    ("buildings", "structures", "the project has no buildings", "structures!=Buildings",
     "and,regulations"),
    ("and/or", "or", "\"or\" already allows both; say \"and\" where both are meant", "", ""),
    ("in accordance to", "in accordance with", "", "", ""),
    ("comply to", "comply with", "", "", ""),
    ("compliance to", "compliance with", "", "", ""),
    ("prior to", "before", "plainer", "", ""),
    ("in order to", "to", "plainer", "", ""),
    ("utilize", "use", "plainer", "", ""),
    ("utilise", "use", "plainer", "", ""),
    ("must", "shall", "a specification says \"shall\" for what is required", "", ""),
    ("etc.", "", "list what is meant: \"etc.\" cannot be priced or enforced", "", ""),
    ("as necessary", "", "say what is necessary, or who decides", "", ""),
]
