from dataclasses import dataclass, field


@dataclass
class Entity:
    entity_id: str
    state: str
    attributes: dict = field(default_factory=dict)

    @property
    def domain(self) -> str:
        return self.entity_id.split(".")[0]

    @property
    def unit(self) -> str:
        return self.attributes.get("unit_of_measurement", "")

    @property
    def friendly_name(self) -> str:
        return self.attributes.get("friendly_name", self.entity_id)

    @property
    def device_class(self) -> str:
        return self.attributes.get("device_class", "")

    @property
    def state_class(self) -> str:
        return self.attributes.get("state_class", "")
