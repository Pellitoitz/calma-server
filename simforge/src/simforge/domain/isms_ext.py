"""ISMS extensions on top of the FROZEN ISMS 0.1 core (domain/isms.py is part of the LLM benchmark V1 contract).

`SimModel` = ISMSModel + optional extension blocks: `availability` (calendars, shifts, breaks, exceptions,
operation policies; engine >= 0.6.0) and `production` (product mix, product-specific processing/routing, setups;
engine >= 0.7.0). A model without extension blocks serialises exactly as an ISMS 0.1 model, so
its content_hash (and every approval bound to it) is unchanged.

The frozen verifier/compiler only understands the core: `core()` returns that view; extension blocks are validated by
validation/availability.py and executed by the engine through `CalendarCompiledModel`.
"""

from __future__ import annotations

from pydantic import model_serializer

from .calendar import AvailabilitySpec
from .isms import ISMSModel
from .production import ProductionSpec

EXTENSION_KEYS = ("availability", "production")


class SimModel(ISMSModel):
    availability: AvailabilitySpec | None = None
    production: ProductionSpec | None = None

    @property
    def has_extensions(self) -> bool:
        return any(getattr(self, k) is not None for k in EXTENSION_KEYS)

    @model_serializer(mode="wrap")
    def _omit_empty_extensions(self, handler):
        d = handler(self)
        if isinstance(d, dict):
            for k in EXTENSION_KEYS:
                if k in d and d[k] is None:
                    d.pop(k)
        return d

    def core(self) -> ISMSModel:
        """The ISMS 0.1 view (extension blocks removed) for the frozen verifier/compiler."""
        data = self.model_dump(mode="json")
        for k in EXTENSION_KEYS:
            data.pop(k, None)
        return ISMSModel.model_validate(data)


def as_sim_model(model: ISMSModel) -> SimModel:
    return model if isinstance(model, SimModel) else SimModel.model_validate(model.model_dump(mode="json"))
