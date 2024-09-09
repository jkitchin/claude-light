#!/bin/bash

sudo cp claude.service /etc/systemd/system
sudo systemctl daemon-reload
sudo systemctl enable claude.service
sudo systemctl start claude.service

#end
