"""Tests for the translation project (ported to pytest).

Every test receives ``module`` — your solution module — and uses ``requires`` so
an unwritten function is reported as "not defined" instead of crashing.
"""
from im_pytest import requires

CODON_MAP = {
    'TTT': 'F', 'TTC': 'F', 'TTA': 'L', 'TTG': 'L', 'TCT': 'S', 'TCC': 'S',
    'TCA': 'S', 'TCG': 'S', 'TAT': 'Y', 'TAC': 'Y', 'TAA': '*', 'TAG': '*',
    'TGT': 'C', 'TGC': 'C', 'TGA': '*', 'TGG': 'W', 'CTT': 'L', 'CTC': 'L',
    'CTA': 'L', 'CTG': 'L', 'CCT': 'P', 'CCC': 'P', 'CCA': 'P', 'CCG': 'P',
    'CAT': 'H', 'CAC': 'H', 'CAA': 'Q', 'CAG': 'Q', 'CGT': 'R', 'CGC': 'R',
    'CGA': 'R', 'CGG': 'R', 'ATT': 'I', 'ATC': 'I', 'ATA': 'I', 'ATG': 'M',
    'ACT': 'T', 'ACC': 'T', 'ACA': 'T', 'ACG': 'T', 'AAT': 'N', 'AAC': 'N',
    'AAA': 'K', 'AAG': 'K', 'AGT': 'S', 'AGC': 'S', 'AGA': 'R', 'AGG': 'R',
    'GTT': 'V', 'GTC': 'V', 'GTA': 'V', 'GTG': 'V', 'GCT': 'A', 'GCC': 'A',
    'GCA': 'A', 'GCG': 'A', 'GAT': 'D', 'GAC': 'D', 'GAA': 'E', 'GAG': 'E',
    'GGT': 'G', 'GGC': 'G', 'GGA': 'G', 'GGG': 'G',
}


@requires.codon_map
def test_codon_map(module):
    assert module.codon_map == CODON_MAP


@requires.translate_codon
def test_translate_codon(module):
    assert module.translate_codon("ATG") == "M"
    assert module.translate_codon("TAA") == "*"
    assert module.translate_codon("ACG") == "T"
    assert module.translate_codon("NNN") == "?"      # invalid codon
    assert module.translate_codon("atg") == "M"      # lowercase (added by audit)


@requires.split_codons
def test_split_codons(module):
    assert module.split_codons("AAATTTCCCGGG") == ["AAA", "TTT", "CCC", "GGG"]
    assert module.split_codons("ATG") == ["ATG"]
    assert module.split_codons("") == []             # empty (added by audit)


@requires.translate_orf
def test_translate_orf(module):
    assert module.translate_orf("ATGCCCATGTGA") == "MPM*"
    assert module.translate_orf("ATGATNATGTGA") == "M?M*"
    assert module.translate_orf("ATGTGA") == "M*"
