#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os

""" Bot Configuration """


class DefaultConfig:
    """ Bot Configuration """

    PORT = 3978
    APP_ID = os.environ.get("MicrosoftAppId", "4ea2018c-ea0d-4c37-b902-77345757db06")
    APP_PASSWORD = os.environ.get("MicrosoftAppPassword", "t_x8Q~NqaRcrmnXpXoUyV_FMgqdKbQL899N3jb2p")
