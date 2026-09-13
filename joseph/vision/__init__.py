"""vision / geo osint evidence layer.

design boundary (from the reference framework and enforced here):
    - this is NOT an unrestricted biometric surveillance tool.
    - face recognition, scene matching, and perceptual hashing are pluggable evidence
      channels. they are disabled by default and return CANNOT_RESOLVE unless an
      explicitly authorized backend + corpus is wired in. joseph ships none.
    - the only channels enabled out of the box are deterministic and metadata-based:
      exif/gps extraction and content provenance.
    - visual similarity is evidence for a candidate, never proof of identity.
    - independent evidence streams (visual, textual, geographic) are kept separate and
      only correlated by the evidence engine, which preserves the epistemic firewall.
"""
