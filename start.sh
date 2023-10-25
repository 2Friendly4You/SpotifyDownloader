#!/bin/bash
nohup gunicorn --bind 192.168.0.246:1234 --workers 8 app:app &