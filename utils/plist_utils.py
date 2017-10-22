"""
Simplified version of biplist - Python plist parser and generator.
Full version may be found here: https://bitbucket.org/wooster/biplist

Plist parsing example:

    from biplist import *
    try:
        plist = readPlist("example.plist")
        print plist
    except (InvalidPlistException, NotBinaryPlistException), e:
        print "Not a plist:", e
"""

import datetime
import plistlib
import sys
import io
from collections import namedtuple
from struct import unpack, unpack_from


__all__ = [
    'Uid', 'Data', 'read_plist', 'read_plist_from_string',
    'InvalidPlistException', 'NotBinaryPlistException'
]

# Apple uses Jan 1, 2001 as a base for all plist date/times.
apple_reference_date = datetime.datetime.utcfromtimestamp(978307200)


class Uid(object):
    """Wrapper around integers for representing UID values. This
       is used in keyed archiving."""
    integer = 0

    def __init__(self, integer):
        self.integer = integer

    def __repr__(self):
        return "Uid(%d)" % self.integer

    def __eq__(self, other):
        if isinstance(self, Uid) and isinstance(other, Uid):
            return self.integer == other.integer
        return False

    def __cmp__(self, other):
        return self.integer - other.integer

    def __lt__(self, other):
        return self.integer < other.integer

    def __hash__(self):
        return self.integer

    def __int__(self):
        return int(self.integer)


class Data(bytes):
    """Wrapper around bytes to distinguish Data values."""


class InvalidPlistException(Exception):
    """Raised when the plist is incorrectly formatted."""


class NotBinaryPlistException(Exception):
    """Raised when a binary plist was expected but not encountered."""


def read_plist(path_or_file):
    """Raises NotBinaryPlistException, InvalidPlistException"""
    did_open = False
    result = None
    if isinstance(path_or_file, str):
        path_or_file = open(path_or_file, 'rb')
        did_open = True

    try:
        reader = PlistReader(path_or_file)
        result = reader.parse()
    except NotBinaryPlistException as e:
        try:
            path_or_file.seek(0)
            result = None
            if hasattr(plistlib, 'loads'):
                contents = None
                if isinstance(path_or_file, str):
                    with open(path_or_file, 'rb') as f:
                        contents = f.read()
                else:
                    contents = path_or_file.read()
                result = plistlib.loads(contents)
            else:
                result = plistlib.readPlist(path_or_file)
            result = wrap_data_object(result, for_binary=True)
        except Exception as e:
            raise InvalidPlistException(e)
    finally:
        if did_open:
            path_or_file.close()
    return result


def wrap_data_object(o, for_binary=False):
    if isinstance(o, Data) and not for_binary:
        v = sys.version_info
        if not (v[0] >= 3 and v[1] >= 4):
            o = plistlib.Data(o)
    elif isinstance(o, (bytes, plistlib.Data)) and for_binary:
        if hasattr(o, 'data'):
            o = Data(o.data)
    elif isinstance(o, tuple):
        o = wrap_data_object(list(o), for_binary)
        o = tuple(o)
    elif isinstance(o, list):
        for i in range(len(o)):
            o[i] = wrap_data_object(o[i], for_binary)
    elif isinstance(o, dict):
        for k in o:
            o[k] = wrap_data_object(o[k], for_binary)
    return o


def read_plist_from_string(data):
    return read_plist(io.BytesIO(data))


def is_stream_binary_plist(stream):
    stream.seek(0)
    header = stream.read(7)
    if header == b'bplist0':
        return True
    else:
        return False


PlistTrailer = namedtuple('PlistTrailer',
                          'offsetSize, objectRefSize, offsetCount, topLevelObjectNumber, offsetTableOffset')
PlistByteCounts = namedtuple('PlistByteCounts',
                             'nullBytes, boolBytes, intBytes, realBytes, dateBytes, dataBytes, stringBytes, uidBytes, arrayBytes, setBytes, dictBytes')


class PlistReader(object):
    file = None
    contents = ''
    offsets = None
    trailer = None
    currentOffset = 0

    def __init__(self, fileOrStream):
        """Raises NotBinaryPlistException."""
        self.reset()
        self.file = fileOrStream

    def parse(self):
        return self.readRoot()

    def reset(self):
        self.trailer = None
        self.contents = ''
        self.offsets = []
        self.currentOffset = 0

    def readRoot(self):
        result = None
        self.reset()
        # Get the header, make sure it's a valid file.
        if not is_stream_binary_plist(self.file):
            raise NotBinaryPlistException()
        self.file.seek(0)
        self.contents = self.file.read()
        if len(self.contents) < 32:
            raise InvalidPlistException("File is too short.")
        trailerContents = self.contents[-32:]
        try:
            self.trailer = PlistTrailer._make(unpack("!xxxxxxBBQQQ", trailerContents))
            offset_size = self.trailer.offsetSize * self.trailer.offsetCount
            offset = self.trailer.offsetTableOffset
            offset_contents = self.contents[offset:offset + offset_size]
            offset_i = 0
            while offset_i < self.trailer.offsetCount:
                begin = self.trailer.offsetSize * offset_i
                tmp_contents = offset_contents[begin:begin + self.trailer.offsetSize]
                tmp_sized = self.getSizedInteger(tmp_contents, self.trailer.offsetSize)
                self.offsets.append(tmp_sized)
                offset_i += 1
            self.setCurrentOffsetToObjectNumber(self.trailer.topLevelObjectNumber)
            result = self.readObject()
        except TypeError as e:
            raise InvalidPlistException(e)
        return result

    def setCurrentOffsetToObjectNumber(self, objectNumber):
        self.currentOffset = self.offsets[objectNumber]

    def readObject(self):
        result = None
        tmp_byte = self.contents[self.currentOffset:self.currentOffset + 1]
        marker_byte = unpack("!B", tmp_byte)[0]
        format = (marker_byte >> 4) & 0x0f
        extra = marker_byte & 0x0f
        self.currentOffset += 1

        def proc_extra(extra):
            if extra == 0b1111:
                # self.currentOffset += 1
                extra = self.readObject()
            return extra

        # bool, null, or fill byte
        if format == 0b0000:
            if extra == 0b0000:
                result = None
            elif extra == 0b1000:
                result = False
            elif extra == 0b1001:
                result = True
            elif extra == 0b1111:
                pass  # fill byte
            else:
                raise InvalidPlistException("Invalid object found at offset: %d" % (self.currentOffset - 1))
        # int
        elif format == 0b0001:
            extra = proc_extra(extra)
            result = self.readInteger(pow(2, extra))
        # real
        elif format == 0b0010:
            extra = proc_extra(extra)
            result = self.readReal(extra)
        # date
        elif format == 0b0011 and extra == 0b0011:
            result = self.readDate()
        # data
        elif format == 0b0100:
            extra = proc_extra(extra)
            result = self.readData(extra)
        # ascii string
        elif format == 0b0101:
            extra = proc_extra(extra)
            result = self.readAsciiString(extra)
        # Unicode string
        elif format == 0b0110:
            extra = proc_extra(extra)
            result = self.readUnicode(extra)
        # uid
        elif format == 0b1000:
            result = self.readUid(extra)
        # array
        elif format == 0b1010:
            extra = proc_extra(extra)
            result = self.readArray(extra)
        # set
        elif format == 0b1100:
            extra = proc_extra(extra)
            result = set(self.readArray(extra))
        # dict
        elif format == 0b1101:
            extra = proc_extra(extra)
            result = self.readDict(extra)
        else:
            raise InvalidPlistException("Invalid object found: {format: %s, extra: %s}" % (bin(format), bin(extra)))
        return result

    def readInteger(self, byteSize):
        result = 0
        original_offset = self.currentOffset
        data = self.contents[self.currentOffset:self.currentOffset + byteSize]
        result = self.getSizedInteger(data, byteSize, as_number=True)
        self.currentOffset = original_offset + byteSize
        return result

    def readReal(self, length):
        result = 0.0
        to_read = pow(2, length)
        data = self.contents[self.currentOffset:self.currentOffset + to_read]
        if length == 2:  # 4 bytes
            result = unpack('>f', data)[0]
        elif length == 3:  # 8 bytes
            result = unpack('>d', data)[0]
        else:
            raise InvalidPlistException("Unknown real of length %d bytes" % to_read)
        return result

    def readRefs(self, count):
        refs = []
        i = 0
        while i < count:
            fragment = self.contents[self.currentOffset:self.currentOffset + self.trailer.objectRefSize]
            ref = self.getSizedInteger(fragment, len(fragment))
            refs.append(ref)
            self.currentOffset += self.trailer.objectRefSize
            i += 1
        return refs

    def readArray(self, count):
        result = []
        values = self.readRefs(count)
        i = 0
        while i < len(values):
            self.setCurrentOffsetToObjectNumber(values[i])
            value = self.readObject()
            result.append(value)
            i += 1
        return result

    def readDict(self, count):
        result = {}
        keys = self.readRefs(count)
        values = self.readRefs(count)
        i = 0
        while i < len(keys):
            self.setCurrentOffsetToObjectNumber(keys[i])
            key = self.readObject()
            self.setCurrentOffsetToObjectNumber(values[i])
            value = self.readObject()
            result[key] = value
            i += 1
        return result

    def readAsciiString(self, length):
        result = unpack("!%ds" % length, self.contents[self.currentOffset:self.currentOffset + length])[0]
        self.currentOffset += length
        return str(result.decode('ascii'))

    def readUnicode(self, length):
        actual_length = length * 2
        data = self.contents[self.currentOffset:self.currentOffset + actual_length]
        # unpack not needed?!! data = unpack(">%ds" % (actual_length), data)[0]
        self.currentOffset += actual_length
        return data.decode('utf_16_be')

    def readDate(self):
        result = unpack(">d", self.contents[self.currentOffset:self.currentOffset + 8])[0]
        # Use timedelta to workaround time_t size limitation on 32-bit python.
        result = datetime.timedelta(seconds=result) + apple_reference_date
        self.currentOffset += 8
        return result

    def readData(self, length):
        result = self.contents[self.currentOffset:self.currentOffset + length]
        self.currentOffset += length
        return Data(result)

    def readUid(self, length):
        return Uid(self.readInteger(length + 1))

    def getSizedInteger(self, data, byteSize, as_number=False):
        """Numbers of 8 bytes are signed integers when they refer to numbers, but unsigned otherwise."""
        result = 0
        # 1, 2, and 4 byte integers are unsigned
        if byteSize == 1:
            result = unpack('>B', data)[0]
        elif byteSize == 2:
            result = unpack('>H', data)[0]
        elif byteSize == 4:
            result = unpack('>L', data)[0]
        elif byteSize == 8:
            if as_number:
                result = unpack('>q', data)[0]
            else:
                result = unpack('>Q', data)[0]
        elif byteSize <= 16:
            # Handle odd-sized or integers larger than 8 bytes
            # Don't naively go over 16 bytes, in order to prevent infinite loops.
            result = 0
            if hasattr(int, 'from_bytes'):
                result = int.from_bytes(data, 'big')
            else:
                for byte in data:
                    if not isinstance(byte, int):  # Python3.0-3.1.x return ints, 2.x return str
                        byte = unpack_from('>B', byte)[0]
                    result = (result << 8) | byte
        else:
            raise InvalidPlistException("Encountered integer longer than 16 bytes.")
        return result
