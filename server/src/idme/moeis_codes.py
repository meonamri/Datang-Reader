"""
MOEIS Absence Reason Codes for IDME Portal

Phase 1: All absences default to N0040027 (PONTENG - MALAS KE SEKOLAH).
The full category/reason structure is defined here for future expansion.

Reference: ALASAN TIDAK HADIR KE SEKOLAH - SISTEM IDME
8 main categories with 97+ reason codes.
"""

# =============================================================================
# DEFAULT ABSENCE REASON (Phase 1 - hardcoded for all absences)
# =============================================================================

DEFAULT_CATEGORY = 'N'
DEFAULT_CATEGORY_MALAY = 'PONTENG'
DEFAULT_SEBAB_ID = 'N0040027'
DEFAULT_SEBAB_DESCRIPTION = 'MALAS KE SEKOLAH'


# =============================================================================
# MOEIS CATEGORY CODES (as displayed in IDME portal dropdowns)
# =============================================================================

MOEIS_CATEGORIES = {
    'B': 'AKTIVITI LUAR SEKOLAH',
    'D': 'MASALAH KESIHATAN',
    'E': 'DIGANTUNG SEKOLAH',
    'I': 'MASALAH PERIBADI',
    'J': 'MASALAH KELUARGA',
    'K': 'ANCAMAN KESELAMATAN',
    'L': 'BENCANA ALAM',
    'M': 'KEBENARAN PENGETUA/GURU BESAR',
    'N': 'PONTENG',
    'A': 'PDPR',
    'G': 'PENGGILIRAN PEPERIKSAAN',
    'P': 'SEKOLAH DALAM HOSPITAL',
}


# =============================================================================
# COMPLETE MOEIS SEBAB CODES (97 codes across all categories)
# =============================================================================

COMPLETE_MOEIS_SEBAB = {
    # B: AKTIVITI LUAR SEKOLAH (1 code)
    'B0010073': {'category': 'B', 'keterangan': 'WAKIL SEKOLAH'},

    # D: MASALAH KESIHATAN (42 codes)
    'D0260001': {'category': 'D', 'keterangan': 'MAKLUMAN IBU BAPA PENJAGA'},
    'D0260020': {'category': 'D', 'keterangan': 'KECEDERAAN/PATAH TULANG'},
    'D0260030': {'category': 'D', 'keterangan': 'SURAT CUTI SAKIT HOSPITAL/KLINIK'},
    'D0060063': {'category': 'D', 'keterangan': 'IMUNISASI RENDAH'},
    'D0010075': {'category': 'D', 'keterangan': 'DEMAM'},
    'D0130070': {'category': 'D', 'keterangan': 'TANTRUM (MBK)'},
    'D0020059': {'category': 'D', 'keterangan': 'TEMUJANJI HOSPITAL/KLINIK'},
    'D0010058': {'category': 'D', 'keterangan': 'MENJALANI TERAPI/RAWATAN/KUARANTIN'},
    'D0140071': {'category': 'D', 'keterangan': 'TIDAK MELEPASI SARINGAN KESIHATAN (MBK)'},
    'D0160073': {'category': 'D', 'keterangan': 'MENDAPATKAN RAWATAN TRADISIONAL'},
    'D0170074': {'category': 'D', 'keterangan': 'KEMURUNGAN'},
    'D0050005': {'category': 'D', 'keterangan': 'BATUK KOKOL'},
    'D0060006': {'category': 'D', 'keterangan': 'BEGUK'},
    'D0070007': {'category': 'D', 'keterangan': 'CACAR AIR'},
    'D0080008': {'category': 'D', 'keterangan': 'CHIKUNGUNYA'},
    'D0010001': {'category': 'D', 'keterangan': 'COVID 19 BERGEJALA'},
    'D0020002': {'category': 'D', 'keterangan': 'COVID 19 DENGAN KEBENARAN IBUBAPA'},
    'D0030003': {'category': 'D', 'keterangan': 'COVID 19 DIKUARANTIN'},
    'D0040004': {'category': 'D', 'keterangan': 'COVID 19 PENGGILIRAN'},
    'D0090009': {'category': 'D', 'keterangan': 'DENGGI'},
    'D0100010': {'category': 'D', 'keterangan': 'SWINE FLU (H1N1)'},
    'D0110011': {'category': 'D', 'keterangan': 'HEPATITIS'},
    'D0120012': {'category': 'D', 'keterangan': 'HAND, FOOT AND MOUTH DISEASE (HFMD)'},
    'D0130013': {'category': 'D', 'keterangan': 'INFLUENZA'},
    'D0140014': {'category': 'D', 'keterangan': 'JAPANESE ENCEPHALITIS (JE)'},
    'D0150015': {'category': 'D', 'keterangan': 'LEPTOSPIROSIS (PENYAKIT KENCING TIKUS)'},
    'D0160016': {'category': 'D', 'keterangan': 'KUDIS BUTA'},
    'D0170017': {'category': 'D', 'keterangan': 'MALARIA'},
    'D0180018': {'category': 'D', 'keterangan': 'MERS COV'},
    'D0190019': {'category': 'D', 'keterangan': 'SAKIT MATA'},
    'D0200020': {'category': 'D', 'keterangan': 'SARS'},
    'D0210021': {'category': 'D', 'keterangan': 'TAUN'},
    'D0220022': {'category': 'D', 'keterangan': 'TIBI'},
    'D0240024': {'category': 'D', 'keterangan': 'SAKIT MISTIK'},
    'D0250025': {'category': 'D', 'keterangan': 'SAKIT MENTAL'},
    'D0170053': {'category': 'D', 'keterangan': 'TEKANAN EMOSI'},

    # E: DIGANTUNG SEKOLAH (1 code)
    'E0010076': {'category': 'E', 'keterangan': 'DIGANTUNG SEKOLAH'},

    # I: MASALAH PERIBADI (2 codes)
    'I0030026': {'category': 'I', 'keterangan': 'TEKANAN PERASAAN/TRAUMA'},
    'I0070030': {'category': 'I', 'keterangan': 'KESAKITAN AKIBAT HAID/PERMULAAN HAID'},

    # J: MASALAH KELUARGA (14 codes)
    'J0150072': {'category': 'J', 'keterangan': 'BEKERJA'},
    'J0080034': {'category': 'J', 'keterangan': 'BERPINDAH RANDAH'},
    'J0010027': {'category': 'J', 'keterangan': 'PEREBUTAN HAK PENJAGAAN ANAK'},
    'J0040030': {'category': 'J', 'keterangan': 'MENGIKUT KELUARGA BERCUTI/BERKURSUS'},
    'J0050031': {'category': 'J', 'keterangan': 'MENJAGA/MENGURUSKAN AHLI KELUARGA'},
    'J0060032': {'category': 'J', 'keterangan': 'MENJAGA AHLI KELUARGA YANG SAKIT'},
    'J0020028': {'category': 'J', 'keterangan': 'KEMATIAN AHLI KELUARGA TERDEKAT'},
    'J0020025': {'category': 'J', 'keterangan': 'KEMISKINAN/KESEMPITAN HIDUP'},
    'J0090035': {'category': 'J', 'keterangan': 'MASALAH PENGANGKUTAN'},
    'J0070033': {'category': 'J', 'keterangan': 'MENZIARAHI KELUARGA SAKIT'},
    'J1100037': {'category': 'J', 'keterangan': 'BALIK KAMPUNG'},
    'J1200038': {'category': 'J', 'keterangan': 'BERPINDAH KE LUAR NEGARA'},
    'J0010037': {'category': 'J', 'keterangan': 'KRISIS KELUARGA'},
    'J0060029': {'category': 'J', 'keterangan': 'LARI DARI RUMAH'},

    # K: ANCAMAN KESELAMATAN (11 codes)
    'K0130049': {'category': 'K', 'keterangan': 'BINATANG LIAR/BUAS/BERBISA'},
    'K0050041': {'category': 'K', 'keterangan': 'DICULIK'},
    'K0060042': {'category': 'K', 'keterangan': 'GANGGUAN MISTIK/MAKHLUK HALUS'},
    'K0090045': {'category': 'K', 'keterangan': 'GANGGUAN KUMPULAN KONGSI GELAP'},
    'K0070043': {'category': 'K', 'keterangan': 'KEBAKARAN'},
    'K0080044': {'category': 'K', 'keterangan': 'PENGGANAS/LANUN'},
    'K0120048': {'category': 'K', 'keterangan': 'RUSUHAN DI LUAR KAWASAN SEKOLAH'},
    'K0020038': {'category': 'K', 'keterangan': 'UGUTAN DARIPADA PIHAK LUAR'},
    'K0150051': {'category': 'K', 'keterangan': 'MANGSA BULI'},
    'K0160052': {'category': 'K', 'keterangan': 'MANGSA SEKSUAL'},
    'K0180054': {'category': 'K', 'keterangan': 'TIDAK DAPAT DIKESAN/HILANG'},

    # L: BENCANA ALAM (11 codes)
    'L0080059': {'category': 'L', 'keterangan': 'JEREBU'},
    'L0080060': {'category': 'L', 'keterangan': 'KEMALANGAN'},
    'L0010050': {'category': 'L', 'keterangan': 'BANJIR'},
    'L0020051': {'category': 'L', 'keterangan': 'GEMPA BUMI'},
    'L0030052': {'category': 'L', 'keterangan': 'HUJAN LEBAT/RIBUT TAUFAN'},
    'L0040053': {'category': 'L', 'keterangan': 'PENCEMARAN UDARA'},
    'L0050054': {'category': 'L', 'keterangan': 'KEMARAU'},
    'L0060055': {'category': 'L', 'keterangan': 'CUACA PANAS EL NINO'},
    'L0070056': {'category': 'L', 'keterangan': 'PENCEMARAN SISA KIMIA'},
    'L0080058': {'category': 'L', 'keterangan': 'PENCEMARAN ALAM'},
    'L0080057': {'category': 'L', 'keterangan': 'TANAH RUNTUH'},

    # M: KEBENARAN PENGETUA/GURU BESAR (13 codes)
    'M0030060': {'category': 'M', 'keterangan': 'HAJI/UMRAH/KEGIATAN AGAMA'},
    'M0080065': {'category': 'M', 'keterangan': 'PEPERIKSAAN/UJIAN SELAIN KPM'},
    'M0070064': {'category': 'M', 'keterangan': 'PERTANDINGAN/AKTIVITI SELAIN KPM'},
    'M0120069': {'category': 'M', 'keterangan': 'PROSES PERPINDAHAN SEKOLAH'},
    'M0090066': {'category': 'M', 'keterangan': 'TERLIBAT KES JENAYAH'},
    'M0100067': {'category': 'M', 'keterangan': 'TERLIBAT KES TRAFIK'},
    'M0110068': {'category': 'M', 'keterangan': 'URUSAN RASMI AGENSI KERAJAAN'},
    'M0170074': {'category': 'M', 'keterangan': 'LATIHAN/UJIAN LESEN MEMANDU'},
    'M0180075': {'category': 'M', 'keterangan': 'TAHANAN PIHAK BERKUASA'},
    'M0190076': {'category': 'M', 'keterangan': 'TERLIBAT PROSIDING MAHKAMAH'},
    'M0200079': {'category': 'M', 'keterangan': 'PERLINDUNGAN JABATAN KEBAJIKAN MASYARAKAT'},
    'M0200077': {'category': 'M', 'keterangan': 'CUTI SEMESTER KOLEJ VOKASIONAL'},
    'M0200078': {'category': 'M', 'keterangan': 'MENJALANI LATIHAN INDUSTRI'},

    # N: PONTENG (5 codes)
    'N0010024': {'category': 'N', 'keterangan': 'BANGUN LEWAT'},
    'N0040027': {'category': 'N', 'keterangan': 'MALAS KE SEKOLAH'},
    'N0080031': {'category': 'N', 'keterangan': 'KETAGIHAN GAJET'},
    'N0090032': {'category': 'N', 'keterangan': 'TIDAK MENYIAPKAN KERJA SEKOLAH'},
    'N0100033': {'category': 'N', 'keterangan': 'MALAS KE AKTIVITI KOKURIKULUM'},

    # A: PDPR (1 code)
    'A0010072': {'category': 'A', 'keterangan': 'PEMBELAJARAN DI RUMAH'},

    # G: PENGGILIRAN PEPERIKSAAN (1 code)
    'G0010078': {'category': 'G', 'keterangan': 'URUSAN PEPERIKSAAN'},

    # P: SEKOLAH DALAM HOSPITAL (1 code)
    'P0270084': {'category': 'P', 'keterangan': 'SEKOLAH DALAM HOSPITAL'},
}

# =============================================================================
# CURATED QUICK-PICK REASONS (Telegram bot)
# =============================================================================
# The short list of reasons offered as one-tap buttons when a teacher records why
# a student is absent. The full set is still reachable via "More…" -> category ->
# reason (built from MOEIS_CATEGORIES / COMPLETE_MOEIS_SEBAB). Ordered most-common
# first; the default (MALAS KE SEKOLAH) is last so it isn't the easy default tap.
COMMON_SEBAB = [
    'D0010075',  # DEMAM
    'D0260030',  # SURAT CUTI SAKIT HOSPITAL/KLINIK
    'D0260001',  # MAKLUMAN IBU BAPA PENJAGA
    'D0020059',  # TEMUJANJI HOSPITAL/KLINIK
    'J0040030',  # MENGIKUT KELUARGA BERCUTI/BERKURSUS
    'J0020028',  # KEMATIAN AHLI KELUARGA TERDEKAT
    'M0030060',  # HAJI/UMRAH/KEGIATAN AGAMA
    DEFAULT_SEBAB_ID,  # N0040027 MALAS KE SEKOLAH (default)
]


# Reverse lookup: sebab_id -> category
SEBAB_TO_CATEGORY = {
    sebab_id: info['category']
    for sebab_id, info in COMPLETE_MOEIS_SEBAB.items()
}

# Reverse lookup: sebab_id -> description
SEBAB_DESCRIPTIONS = {
    sebab_id: info['keterangan']
    for sebab_id, info in COMPLETE_MOEIS_SEBAB.items()
}
