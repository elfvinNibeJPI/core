"""Tests for the Bond fan device."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import call

from bond_api import Action, DeviceType, Direction
import pytest

from homeassistant import core
from homeassistant.components import fan
from homeassistant.components.bond.const import (
    DOMAIN as BOND_DOMAIN,
    SERVICE_SET_FAN_SPEED_TRACKED_STATE,
)
from homeassistant.components.bond.fan import PRESET_MODE_BREEZE
from homeassistant.components.fan import (
    ATTR_DIRECTION,
    ATTR_PERCENTAGE,
    ATTR_PRESET_MODE,
    ATTR_PRESET_MODES,
    DIRECTION_FORWARD,
    DIRECTION_REVERSE,
    DOMAIN as FAN_DOMAIN,
    SERVICE_SET_DIRECTION,
    SERVICE_SET_PERCENTAGE,
    SERVICE_SET_PRESET_MODE,
)
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_registry import EntityRegistry
from homeassistant.util import utcnow

from .common import (
    help_test_entity_available,
    patch_bond_action,
    patch_bond_action_returns_clientresponseerror,
    patch_bond_device_state,
    setup_platform,
)

from tests.common import async_fire_time_changed


def ceiling_fan(name: str):
    """Create a ceiling fan with given name."""
    return {
        "name": name,
        "type": DeviceType.CEILING_FAN,
        "actions": ["SetSpeed", "SetDirection"],
    }


def ceiling_fan_with_breeze(name: str):
    """Create a ceiling fan with given name with breeze support."""
    return {
        "name": name,
        "type": DeviceType.CEILING_FAN,
        "actions": ["SetSpeed", "SetDirection", "BreezeOn"],
    }


async def turn_fan_on(
    hass: core.HomeAssistant,
    fan_id: str,
    percentage: int | None = None,
    preset_mode: str | None = None,
) -> None:
    """Turn the fan on at the specified speed."""
    service_data = {ATTR_ENTITY_ID: fan_id}
    if preset_mode:
        service_data[fan.ATTR_PRESET_MODE] = preset_mode
    if percentage is not None:
        service_data[fan.ATTR_PERCENTAGE] = percentage
    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_TURN_ON,
        service_data=service_data,
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_entity_registry(hass: core.HomeAssistant):
    """Tests that the devices are registered in the entity registry."""
    await setup_platform(
        hass,
        FAN_DOMAIN,
        ceiling_fan("name-1"),
        bond_version={"bondid": "test-hub-id"},
        bond_device_id="test-device-id",
    )

    registry: EntityRegistry = er.async_get(hass)
    entity = registry.entities["fan.name_1"]
    assert entity.unique_id == "test-hub-id_test-device-id"

    device_registry = dr.async_get(hass)
    device = device_registry.async_get(entity.device_id)
    assert device.configuration_url == "http://some host"


async def test_non_standard_speed_list(hass: core.HomeAssistant):
    """Tests that the device is registered with custom speed list if number of supported speeds differs form 3."""
    await setup_platform(
        hass,
        FAN_DOMAIN,
        ceiling_fan("name-1"),
        bond_device_id="test-device-id",
        props={"max_speed": 6},
    )

    with patch_bond_device_state():
        with patch_bond_action() as mock_set_speed_low:
            await turn_fan_on(hass, "fan.name_1", percentage=100 / 6 * 2)
        mock_set_speed_low.assert_called_once_with(
            "test-device-id", Action.set_speed(2)
        )

        with patch_bond_action() as mock_set_speed_medium:
            await turn_fan_on(hass, "fan.name_1", percentage=100 / 6 * 4)
        mock_set_speed_medium.assert_called_once_with(
            "test-device-id", Action.set_speed(4)
        )

        with patch_bond_action() as mock_set_speed_high:
            await turn_fan_on(hass, "fan.name_1", percentage=100)
        mock_set_speed_high.assert_called_once_with(
            "test-device-id", Action.set_speed(6)
        )


async def test_fan_speed_with_no_max_speed(hass: core.HomeAssistant):
    """Tests that fans without max speed (increase/decrease controls) map speed to HA standard."""
    await setup_platform(
        hass,
        FAN_DOMAIN,
        ceiling_fan("name-1"),
        bond_device_id="test-device-id",
        props={"no": "max_speed"},
        state={"power": 1, "speed": 14},
    )

    assert hass.states.get("fan.name_1").attributes["percentage"] == 100


async def test_turn_on_fan_with_speed(hass: core.HomeAssistant):
    """Tests that turn on command delegates to set speed API."""
    await setup_platform(
        hass, FAN_DOMAIN, ceiling_fan("name-1"), bond_device_id="test-device-id"
    )

    with patch_bond_action() as mock_set_speed, patch_bond_device_state():
        await turn_fan_on(hass, "fan.name_1", percentage=1)

    mock_set_speed.assert_called_with("test-device-id", Action.set_speed(1))


async def test_turn_on_fan_with_percentage_3_speeds(hass: core.HomeAssistant):
    """Tests that turn on command delegates to set speed API."""
    await setup_platform(
        hass, FAN_DOMAIN, ceiling_fan("name-1"), bond_device_id="test-device-id"
    )

    with patch_bond_action() as mock_set_speed, patch_bond_device_state():
        await turn_fan_on(hass, "fan.name_1", percentage=10)

    mock_set_speed.assert_called_with("test-device-id", Action.set_speed(1))

    mock_set_speed.reset_mock()
    with patch_bond_action() as mock_set_speed, patch_bond_device_state():
        await turn_fan_on(hass, "fan.name_1", percentage=50)

    mock_set_speed.assert_called_with("test-device-id", Action.set_speed(2))

    mock_set_speed.reset_mock()
    with patch_bond_action() as mock_set_speed, patch_bond_device_state():
        await turn_fan_on(hass, "fan.name_1", percentage=100)

    mock_set_speed.assert_called_with("test-device-id", Action.set_speed(3))


async def test_turn_on_fan_with_percentage_6_speeds(hass: core.HomeAssistant):
    """Tests that turn on command delegates to set speed API."""
    await setup_platform(
        hass,
        FAN_DOMAIN,
        ceiling_fan("name-1"),
        bond_device_id="test-device-id",
        props={"max_speed": 6},
    )

    with patch_bond_action() as mock_set_speed, patch_bond_device_state():
        await turn_fan_on(hass, "fan.name_1", percentage=10)

    mock_set_speed.assert_called_with("test-device-id", Action.set_speed(1))

    mock_set_speed.reset_mock()
    with patch_bond_action() as mock_set_speed, patch_bond_device_state():
        await turn_fan_on(hass, "fan.name_1", percentage=50)

    mock_set_speed.assert_called_with("test-device-id", Action.set_speed(3))

    mock_set_speed.reset_mock()
    with patch_bond_action() as mock_set_speed, patch_bond_device_state():
        await turn_fan_on(hass, "fan.name_1", percentage=100)

    mock_set_speed.assert_called_with("test-device-id", Action.set_speed(6))


async def test_turn_on_fan_preset_mode(hass: core.HomeAssistant):
    """Tests that turn on command delegates to breeze on API."""
    await setup_platform(
        hass,
        FAN_DOMAIN,
        ceiling_fan_with_breeze("name-1"),
        bond_device_id="test-device-id",
        props={"max_speed": 6},
    )
    assert hass.states.get("fan.name_1").attributes[ATTR_PRESET_MODES] == [
        PRESET_MODE_BREEZE
    ]

    with patch_bond_action() as mock_set_preset_mode, patch_bond_device_state():
        await turn_fan_on(hass, "fan.name_1", preset_mode=PRESET_MODE_BREEZE)

    mock_set_preset_mode.assert_called_with("test-device-id", Action(Action.BREEZE_ON))

    with patch_bond_action() as mock_set_preset_mode, patch_bond_device_state():
        await hass.services.async_call(
            FAN_DOMAIN,
            SERVICE_SET_PRESET_MODE,
            service_data={
                ATTR_PRESET_MODE: PRESET_MODE_BREEZE,
                ATTR_ENTITY_ID: "fan.name_1",
            },
            blocking=True,
        )

    mock_set_preset_mode.assert_called_with("test-device-id", Action(Action.BREEZE_ON))


async def test_turn_on_fan_preset_mode_not_supported(hass: core.HomeAssistant):
    """Tests calling breeze mode on a fan that does not support it raises."""
    await setup_platform(
        hass,
        FAN_DOMAIN,
        ceiling_fan("name-1"),
        bond_device_id="test-device-id",
        props={"max_speed": 6},
    )

    with patch_bond_action(), patch_bond_device_state(), pytest.raises(ValueError):
        await turn_fan_on(hass, "fan.name_1", preset_mode=PRESET_MODE_BREEZE)

    with patch_bond_action(), patch_bond_device_state(), pytest.raises(ValueError):
        await hass.services.async_call(
            FAN_DOMAIN,
            SERVICE_SET_PRESET_MODE,
            service_data={
                ATTR_PRESET_MODE: PRESET_MODE_BREEZE,
                ATTR_ENTITY_ID: "fan.name_1",
            },
            blocking=True,
        )


async def test_turn_on_fan_with_off_with_breeze(hass: core.HomeAssistant):
    """Tests that turn off command delegates to turn off API."""
    await setup_platform(
        hass,
        FAN_DOMAIN,
        ceiling_fan_with_breeze("name-1"),
        bond_device_id="test-device-id",
        state={"breeze": [1, 0, 0]},
    )

    assert (
        hass.states.get("fan.name_1").attributes[ATTR_PRESET_MODE] == PRESET_MODE_BREEZE
    )

    with patch_bond_action() as mock_actions, patch_bond_device_state():
        await turn_fan_on(hass, "fan.name_1", percentage=0)

    assert mock_actions.mock_calls == [
        call("test-device-id", Action(Action.BREEZE_OFF)),
        call("test-device-id", Action.turn_off()),
    ]


async def test_turn_on_fan_without_speed(hass: core.HomeAssistant):
    """Tests that turn on command delegates to turn on API."""
    await setup_platform(
        hass, FAN_DOMAIN, ceiling_fan("name-1"), bond_device_id="test-device-id"
    )

    with patch_bond_action() as mock_turn_on, patch_bond_device_state():
        await turn_fan_on(hass, "fan.name_1")

    mock_turn_on.assert_called_with("test-device-id", Action.turn_on())


async def test_turn_on_fan_with_off_percentage(hass: core.HomeAssistant):
    """Tests that turn off command delegates to turn off API."""
    await setup_platform(
        hass, FAN_DOMAIN, ceiling_fan("name-1"), bond_device_id="test-device-id"
    )

    with patch_bond_action() as mock_turn_off, patch_bond_device_state():
        await turn_fan_on(hass, "fan.name_1", percentage=0)

    mock_turn_off.assert_called_with("test-device-id", Action.turn_off())


async def test_set_speed_off(hass: core.HomeAssistant):
    """Tests that set_speed(off) command delegates to turn off API."""
    await setup_platform(
        hass, FAN_DOMAIN, ceiling_fan("name-1"), bond_device_id="test-device-id"
    )

    with patch_bond_action() as mock_turn_off, patch_bond_device_state():
        await hass.services.async_call(
            FAN_DOMAIN,
            SERVICE_SET_PERCENTAGE,
            service_data={ATTR_ENTITY_ID: "fan.name_1", ATTR_PERCENTAGE: 0},
            blocking=True,
        )
    await hass.async_block_till_done()

    mock_turn_off.assert_called_with("test-device-id", Action.turn_off())


async def test_turn_off_fan(hass: core.HomeAssistant):
    """Tests that turn off command delegates to API."""
    await setup_platform(
        hass, FAN_DOMAIN, ceiling_fan("name-1"), bond_device_id="test-device-id"
    )

    with patch_bond_action() as mock_turn_off, patch_bond_device_state():
        await hass.services.async_call(
            FAN_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: "fan.name_1"},
            blocking=True,
        )
        await hass.async_block_till_done()

    mock_turn_off.assert_called_once_with("test-device-id", Action.turn_off())


async def test_set_speed_belief_speed_zero(hass: core.HomeAssistant):
    """Tests that set power belief service delegates to API."""
    await setup_platform(
        hass, FAN_DOMAIN, ceiling_fan("name-1"), bond_device_id="test-device-id"
    )

    with patch_bond_action() as mock_action, patch_bond_device_state():
        await hass.services.async_call(
            BOND_DOMAIN,
            SERVICE_SET_FAN_SPEED_TRACKED_STATE,
            {ATTR_ENTITY_ID: "fan.name_1", "speed": 0},
            blocking=True,
        )
        await hass.async_block_till_done()

    mock_action.assert_called_once_with(
        "test-device-id", Action.set_power_state_belief(False)
    )


async def test_set_speed_belief_speed_api_error(hass: core.HomeAssistant):
    """Tests that set power belief service delegates to API."""
    await setup_platform(
        hass, FAN_DOMAIN, ceiling_fan("name-1"), bond_device_id="test-device-id"
    )

    with pytest.raises(
        HomeAssistantError
    ), patch_bond_action_returns_clientresponseerror(), patch_bond_device_state():
        await hass.services.async_call(
            BOND_DOMAIN,
            SERVICE_SET_FAN_SPEED_TRACKED_STATE,
            {ATTR_ENTITY_ID: "fan.name_1", "speed": 100},
            blocking=True,
        )
        await hass.async_block_till_done()


async def test_set_speed_belief_speed_100(hass: core.HomeAssistant):
    """Tests that set power belief service delegates to API."""
    await setup_platform(
        hass, FAN_DOMAIN, ceiling_fan("name-1"), bond_device_id="test-device-id"
    )

    with patch_bond_action() as mock_action, patch_bond_device_state():
        await hass.services.async_call(
            BOND_DOMAIN,
            SERVICE_SET_FAN_SPEED_TRACKED_STATE,
            {ATTR_ENTITY_ID: "fan.name_1", "speed": 100},
            blocking=True,
        )
        await hass.async_block_till_done()

    mock_action.assert_any_call("test-device-id", Action.set_power_state_belief(True))
    mock_action.assert_called_with("test-device-id", Action.set_speed_belief(3))


async def test_update_reports_fan_on(hass: core.HomeAssistant):
    """Tests that update command sets correct state when Bond API reports fan power is on."""
    await setup_platform(hass, FAN_DOMAIN, ceiling_fan("name-1"))

    with patch_bond_device_state(return_value={"power": 1, "speed": 1}):
        async_fire_time_changed(hass, utcnow() + timedelta(seconds=30))
        await hass.async_block_till_done()

    assert hass.states.get("fan.name_1").state == "on"


async def test_update_reports_fan_off(hass: core.HomeAssistant):
    """Tests that update command sets correct state when Bond API reports fan power is off."""
    await setup_platform(hass, FAN_DOMAIN, ceiling_fan("name-1"))

    with patch_bond_device_state(return_value={"power": 0, "speed": 1}):
        async_fire_time_changed(hass, utcnow() + timedelta(seconds=30))
        await hass.async_block_till_done()

    assert hass.states.get("fan.name_1").state == "off"


async def test_update_reports_direction_forward(hass: core.HomeAssistant):
    """Tests that update command sets correct direction when Bond API reports fan direction is forward."""
    await setup_platform(hass, FAN_DOMAIN, ceiling_fan("name-1"))

    with patch_bond_device_state(return_value={"direction": Direction.FORWARD}):
        async_fire_time_changed(hass, utcnow() + timedelta(seconds=30))
        await hass.async_block_till_done()

    assert hass.states.get("fan.name_1").attributes[ATTR_DIRECTION] == DIRECTION_FORWARD


async def test_update_reports_direction_reverse(hass: core.HomeAssistant):
    """Tests that update command sets correct direction when Bond API reports fan direction is reverse."""
    await setup_platform(hass, FAN_DOMAIN, ceiling_fan("name-1"))

    with patch_bond_device_state(return_value={"direction": Direction.REVERSE}):
        async_fire_time_changed(hass, utcnow() + timedelta(seconds=30))
        await hass.async_block_till_done()

    assert hass.states.get("fan.name_1").attributes[ATTR_DIRECTION] == DIRECTION_REVERSE


async def test_set_fan_direction(hass: core.HomeAssistant):
    """Tests that set direction command delegates to API."""
    await setup_platform(
        hass, FAN_DOMAIN, ceiling_fan("name-1"), bond_device_id="test-device-id"
    )

    with patch_bond_action() as mock_set_direction, patch_bond_device_state():
        await hass.services.async_call(
            FAN_DOMAIN,
            SERVICE_SET_DIRECTION,
            {ATTR_ENTITY_ID: "fan.name_1", ATTR_DIRECTION: DIRECTION_FORWARD},
            blocking=True,
        )
        await hass.async_block_till_done()

    mock_set_direction.assert_called_once_with(
        "test-device-id", Action.set_direction(Direction.FORWARD)
    )


async def test_fan_available(hass: core.HomeAssistant):
    """Tests that available state is updated based on API errors."""
    await help_test_entity_available(
        hass, FAN_DOMAIN, ceiling_fan("name-1"), "fan.name_1"
    )
