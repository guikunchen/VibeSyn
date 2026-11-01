from opentrons import protocol_api
# from opentrons.commands.commands import transfer
import time

# metadata
metadata = {
    "protocolName": "test-01-03-26",
    "author": "Name <opentrons@example.com>",
    "description": "Heater-Shaker Module GEN1_Extraction",
}

# requirements
requirements = {"robotType": "OT-2", "apiLevel": "2.14"}


# protocol run function

def run(protocol: protocol_api.ProtocolContext):
    heater_shaker_module = protocol.load_module('heaterShakerModuleV1', '10')

    heater_shaker_module.close_labware_latch()
    heater_shaker_module.set_and_wait_for_shake_speed(1400)
    time.sleep(15)
    heater_shaker_module.deactivate_shaker()
    # heater_shaker_module.open_labware_latch()
