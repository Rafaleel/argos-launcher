import pytest

from app.collectors.ra_flags import Flag, Operand, milestone_flag, parse_operand, read_operand, reached

TAIL = "_R:0xG001688fc=4294967040_R:0xR00163da7=1_R:0xT00163e09=1"  # cheat and special-weapon resets: not milestones
GATE = "0xR00163da7=0_0xH00163db6=0_"
MARVIN = GATE + "d0xN00168a90=0_0xN00168a90=1_0xW00168a4d=1_0xH00168a51=4" + TAIL
UNICORN = GATE + "p0xT00168a8d=0_0xT00168a8d=1_0xW00168a4d=1_d0xH00168a51=14_0xH00168a51=13" + TAIL
FELL_DOWN = GATE + "d0xT00168a88=1_0xT00168a88=0_0xW00168a4d=589827" + TAIL
END = GATE + "d0xH0062203f=4_0xH0062203f=5_0xW00168a4d=6" + TAIL


def test_marvin_is_bit_1_of_one_byte():
    assert milestone_flag(MARVIN) == Flag(Operand(0x168A90, "N"), 1)


def test_a_bit_flag_wins_over_a_room_number_that_also_changes():
    assert milestone_flag(UNICORN) == Flag(Operand(0x168A8D, "T"), 1)  # not 0xH168a51 14 -> 13


def test_a_plain_16_bit_pair_is_not_mistaken_for_a_bit_flag():
    rule = "d0xH000010=1_0xH000010=2_d0x001234=0_0x001234=7"
    assert milestone_flag(rule) == Flag(Operand(0x10, "H"), 2)


def test_a_byte_counter_transition_is_accepted_when_there_is_no_bit():
    assert milestone_flag(END) == Flag(Operand(0x62203F, "H"), 5)


def test_transitions_to_zero_and_other_shapes_are_skipped():
    assert milestone_flag(FELL_DOWN) is None
    assert milestone_flag("A:0xH001234=0_M:0xH001235>=5") is None
    assert milestone_flag("") is None


def test_only_the_core_group_is_read():
    assert milestone_flag("0xH0001=1S" + MARVIN) is None
    # 0xS is the bit-6 size, not an alternative-group separator
    assert milestone_flag("d0xS000123=0_0xS000123=1") == Flag(Operand(0x123, "S"), 1)


def test_operands_read_the_right_width_and_order():
    ram = bytes(range(0x10)) + bytes([0b0100_0010, 0xAB, 0xCD, 0xEF, 0x01])
    read = lambda a, n: ram[a:a + n]  # noqa: E731
    assert read_operand(parse_operand("0xH000010"), read) == 0b0100_0010
    assert read_operand(parse_operand("0xN000010"), read) == 1  # bit 1
    assert read_operand(parse_operand("0xS000010"), read) == 1  # bit 6
    assert read_operand(parse_operand("0xM000010"), read) == 0
    assert read_operand(parse_operand("0xL000010"), read) == 0x2 and read_operand(parse_operand("0xU000010"), read) == 0x4
    assert read_operand(parse_operand("0x000011"), read) == 0xCDAB  # 16-bit little-endian
    assert read_operand(parse_operand("0xI000011"), read) == 0xABCD  # 16-bit big-endian
    assert read_operand(parse_operand("0xW000011"), read) == 0xEFCDAB
    assert read_operand(parse_operand("0xG000011"), read) == 0xABCDEF01


def test_reached_compares_the_current_value():
    flag = milestone_flag(MARVIN)
    assert reached(flag, lambda a, n: b"\x02") is True
    assert reached(flag, lambda a, n: b"\x00") is False


def test_unknown_operands_are_refused():
    for bad in ("0xZ000010", "hello", "0xK000010"):
        with pytest.raises(ValueError):
            parse_operand(bad)
