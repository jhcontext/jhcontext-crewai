"""CrewAI crews for rubric-grounded *oral* (multimodal) grading.

Extends the rubric-grounded grading pipeline (Scenarios A/B/C) from text
essays to audio submissions. The feedback agent binds each sentence to a
millisecond window on the source recording rather than a character span on
an essay. A dedicated ``verify_multimodal_binding`` verifier (SDK) checks
the modality-specific span shape.
"""
