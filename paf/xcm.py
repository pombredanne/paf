# SPDX-License-Identifier: BSD-3-Clause
# Copyright(c) 2020 Ericsson AB

#
# xcm.py - A Python API to Extensible Connection-oriented Messaging (XCM).
#

import os
import socket

from ctypes import CDLL, c_void_p, c_char_p, c_long, c_int, c_bool, cast, \
    POINTER, create_string_buffer, byref, get_errno

xcm_c = CDLL("libxcm.so.0", use_errno=True)

xcm_connect_c = xcm_c.xcm_connect
xcm_connect_c.restype = c_void_p
xcm_connect_c.argtypes = [c_char_p, c_int]

xcm_server_c = xcm_c.xcm_server
xcm_server_c.restype = c_void_p
xcm_server_c.argtypes = [c_char_p]

xcm_close_c = xcm_c.xcm_close
xcm_close_c.restype = c_int
xcm_close_c.argtypes = [c_void_p]

xcm_finish_c = xcm_c.xcm_finish
xcm_finish_c.restype = c_int
xcm_finish_c.argtypes = [c_void_p]

xcm_send_c = xcm_c.xcm_send
xcm_send_c.restype = c_int
xcm_send_c.argtypes = [c_void_p, c_void_p, c_long]

xcm_receive_c = xcm_c.xcm_receive
xcm_receive_c.restype = c_int
xcm_receive_c.argtypes = [c_void_p, c_void_p, c_long]

xcm_accept_c = xcm_c.xcm_accept
xcm_accept_c.restype = c_void_p
xcm_accept_c.argtypes = [c_void_p]

xcm_await_c = xcm_c.xcm_await
xcm_await_c.restype = c_int
xcm_await_c.argtypes = [c_void_p, c_int]

xcm_fd_c = xcm_c.xcm_fd
xcm_fd_c.restype = c_int
xcm_fd_c.argtypes = [c_void_p]

xcm_set_blocking_c = xcm_c.xcm_set_blocking
xcm_set_blocking_c.restype = c_int
xcm_set_blocking_c.argtypes = [c_void_p, c_bool]

xcm_is_blocking_c = xcm_c.xcm_is_blocking
xcm_is_blocking_c.restype = c_bool
xcm_is_blocking_c.argtypes = [c_void_p]

ATTR_TYPE_BOOL = 1
ATTR_TYPE_INT64 = 2
ATTR_TYPE_STR = 3
ATTR_TYPE_BIN = 4

xcm_attr_get_c = xcm_c.xcm_attr_get
xcm_attr_get_c.restype = c_int
xcm_attr_get_c.argtypes = \
    [c_void_p, c_char_p, POINTER(c_int), c_void_p, c_long]

MAX_MSG = 65535

SO_RECEIVABLE = (1 << 0)
SO_SENDABLE = (1 << 1)
SO_ACCEPTABLE = (1 << 2)

NONBLOCK = (1 << 0)


def _conv_attr(attr_type, attr_value, attr_len):
    if attr_type.value == ATTR_TYPE_BOOL:
        bool_value = cast(attr_value.raw, POINTER(c_bool))
        return bool_value.contents.value
    elif attr_type.value == ATTR_TYPE_INT64:
        int_value = cast(attr_value.raw, POINTER(c_long))
        return int_value.contents.value
    elif attr_type.value == ATTR_TYPE_STR:
        return bytes(attr_value.value).decode('utf-8')
    elif attr_type.value == ATTR_TYPE_BIN:
        return bytes(attr_value.raw)[:attr_len]
    else:
        raise ValueError("Invalid argument type %d" % attr_type.value)


def _assure_open(fun):
    def assure_open_wrap(self, *args, **kwargs):
        assert self.xcm_socket is not None
        return fun(self, *args, **kwargs)
    return assure_open_wrap


class Socket:
    def __init__(self, xcm_socket):
        self.xcm_socket = xcm_socket
        self.condition = 0

    @_assure_open
    def close(self):
        if self.xcm_socket is not None:
            xcm_close_c(self.xcm_socket)
            self.xcm_socket = None

    @_assure_open
    def finish(self):
        rc = xcm_finish_c(self.xcm_socket)
        if rc < 0:
            _raise_io_err()

    @_assure_open
    def set_blocking(self, val):
        xcm_set_blocking_c(self.xcm_socket, val)

    @_assure_open
    def is_blocking(self):
        return xcm_is_blocking_c(self.xcm_socket)

    @_assure_open
    # await is a keyword in recent Python versions
    def update(self, condition):
        if condition != self.condition:
            rc = xcm_await_c(self.xcm_socket, condition)
            if rc < 0:
                raise ValueError("invalid condition: '%d'" % condition)
            self.condition = condition

    @_assure_open
    def fileno(self):
        rc = xcm_fd_c(self.xcm_socket)
        if rc < 0:
            _raise_io_err()
        return rc

    @_assure_open
    def get_attr(self, attr_name):
        attr_type = c_int()
        attr_capacity = 1024
        attr_value = create_string_buffer(attr_capacity)
        rc = xcm_attr_get_c(self.xcm_socket, attr_name.encode('utf-8'),
                            byref(attr_type), attr_value, attr_capacity)
        if rc < 0:
            _raise_io_err()
        return _conv_attr(attr_type, attr_value, rc)

    def __del__(self):
        if self.xcm_socket is not None:
            self.close()


def _raise_io_err():
    _errno = get_errno()
    raise error(_errno, os.strerror(_errno))


class error(socket.error):
    pass


class ConnectionSocket(Socket):
    def __init__(self, xcm_socket):
        Socket.__init__(self, xcm_socket)

    def send(self, msg):
        rc = xcm_send_c(self.xcm_socket, msg, len(msg))
        if rc < 0:
            _raise_io_err()
        return 0

    def receive(self):
        buf = create_string_buffer(MAX_MSG)
        rc = xcm_receive_c(self.xcm_socket, byref(buf), MAX_MSG)
        if rc < 0:
            _raise_io_err()
        return bytes(buf.raw[:rc])


class ServerSocket(Socket):
    def __init__(self, xcm_socket):
        Socket.__init__(self, xcm_socket)

    def accept(self):
        xcm_socket = xcm_accept_c(self.xcm_socket)
        if xcm_socket:
            return ConnectionSocket(xcm_socket)
        else:
            _raise_io_err()


def connect(addr, flags):
    xcm_socket = xcm_connect_c(addr.encode('utf-8'), flags)
    if xcm_socket:
        return ConnectionSocket(xcm_socket)
    else:
        _raise_io_err()


def server(addr):
    xcm_socket = xcm_server_c(addr.encode('utf-8'))
    if xcm_socket:
        return ServerSocket(xcm_socket)
    else:
        _raise_io_err()
