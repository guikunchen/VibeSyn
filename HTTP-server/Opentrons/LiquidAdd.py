import time
from opentrons import protocol_api
import json
import re

metadata = {
    "protocolName": "test-01-05-29",
    "author": "Name <opentrons@example.com>",
    "description": "Simple protocol to get started using the OT-2",
}
requirements = {"robotType": "OT-2", "apiLevel": "2.14"}


def run(protocol: protocol_api.ProtocolContext):
    plate_1 = protocol.load_labware("autoopt_10_wellplate_10000ul", location="4")
    tiprack_300 = protocol.load_labware("opentrons_96_tiprack_300ul", location="6")
    tiprack_1000 = protocol.load_labware("autoopt_96_tiprack_1000ul", location="5")
    plate_2 = protocol.load_labware("unchained_8_tuberack_20000ul", location="2")
    pipette_300 = protocol.load_instrument("p300_single", mount="left", tip_racks=[tiprack_300])
    pipette_1000 = protocol.load_instrument('p1000_single', mount="right", tip_racks=[tiprack_1000])

    Volume_Base = 1000
    Tip_No_300 = 4
    Tip_No_1000 = 4
    Vial_No = 1
    data = {"organic_extractants": [["A1", 1.0], ["A2", 2.0]], "aqueous_extractant": ["A3", 1.0], "other_additive": ["A4", 0.0]}
    LiquidAdd_List = data["organic_extractants"] + [data["aqueous_extractant"]]
    if data["other_additive"] != ["N/A", 0.0]:
        LiquidAdd_List.append(data["other_additive"])
    
    if (Vial_No % 2) == 0:
        Vial_No = Vial_No - 2
    else:
        Vial_No = Vial_No

    for i in range(len(LiquidAdd_List)):
        Volume = LiquidAdd_List[i][1] * Volume_Base
        Source = LiquidAdd_List[i][0]
        if Volume <= 300:
            j = Tip_No_300 + i - 1
            pipette_300.pick_up_tip(tiprack_300.wells()[j])
            pipette_300.aspirate(Volume, plate_2[Source])
            pipette_300.dispense(Volume, plate_1.wells()[Vial_No])
            time.sleep(1)
            pipette_300.aspirate(20, plate_1.wells()[Vial_No])
            pipette_300.drop_tip()
        else:
            cycle = int((Volume + 1000 - 1) // 1000)
            j = Tip_No_1000 + i - 1
            pipette_1000.pick_up_tip(tiprack_1000.wells()[j])
            Volume = round(Volume / cycle, 1)
            for k in range(cycle):
                pipette_1000.aspirate(Volume, plate_2[Source])
                pipette_1000.dispense(Volume, plate_1.wells()[Vial_No])
                time.sleep(1)
            pipette_1000.drop_tip()
