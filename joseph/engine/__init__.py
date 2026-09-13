"""joseph engine -> the deterministic osint pipeline.

stage order (mirrors the investigation architecture):

    seed -> grammar -> generator -> mutation -> scoring
         -> providers -> normalize -> relevance
         -> entities -> resolution -> graph -> evidence
"""
