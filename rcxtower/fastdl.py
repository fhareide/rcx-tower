"""The fast-download stub for "quad-rate" firmware download.

The ROM of the RCX only speaks 2400 baud with every byte followed by its complement.
This 88-byte H8 program is downloaded and started like a firmware; it switches
the RCX to 4800 baud without complement bytes, after which the real firmware
can be sent about three times as quickly.

The stub is fastdl.srec from firmdl3 by Kekoa Proudfoot (also used by NQC),
distributed under the Mozilla Public License 1.0. It is reproduced here
unchanged; stub() makes the one adaptation the USB tower needs.
"""

STUB = bytes.fromhex(
    "7906000F6B86EE807906EE646DF67906EE745E003B9A0B877906EE5E5E000688"
    "7FD87250FE673ED918EE6A8EEF51FE026A8EEF06FE0D6A8EEE5E5470446F2079"
    "6F7520627974652C207768656E2049206B6E6F636B3F0000")

# "bclr #5,@0xd8:8": clears the parity enable bit of the serial mode register of the RCX
_CLEAR_PARITY = bytes.fromhex("7FD87250")


def stub(keep_parity=True):
    """The stub to send. The USB tower always sends an odd parity bit, so for it the
    instruction that turns parity off on the RCX is replaced by two NOPs."""
    if not keep_parity:
        return STUB
    at = STUB.find(_CLEAR_PARITY)
    if at < 0 or at % 2:
        raise ValueError("the fast download stub does not look as expected")
    return STUB[:at] + bytes(len(_CLEAR_PARITY)) + STUB[at + len(_CLEAR_PARITY):]
