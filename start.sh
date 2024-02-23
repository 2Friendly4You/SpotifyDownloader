#!/bin/bash

# Configuration
APP_NAME="SpotifyDownloader"
COMMANDLINE_PARAMETERS="" # Add any additional parameters for your app here.
PID_FILE="./$APP_NAME.pid"
LOG_FILE="./$APP_NAME.log"
APP_COMMAND="gunicorn --bind 192.168.0.246:8900 --workers 8 app:app"

# Function to start the app
do_start() {
    if [ -e "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "The $APP_NAME is already running, try restart or stop."
            return 1
        else
            echo "$PID_FILE found, but no server running. Possibly your previously started server crashed."
            rm -f "$PID_FILE"
        fi
    fi

    if [ $(id -u) -eq 0 ]; then
        echo "WARNING! For security reasons, DO NOT RUN THE SERVER AS ROOT."
        for _ in {1..10}; do echo -n "!"; sleep 1; done
        echo
    fi

    echo "Starting the $APP_NAME..."
    nohup $APP_COMMAND $COMMANDLINE_PARAMETERS > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    if [ $? -eq 0 ]; then
        echo "$APP_NAME started, for details please view the log file."
    else
        echo "$APP_NAME could not start."
        return 2
    fi
}

# Function to stop the app
do_stop() {
    if [ ! -e "$PID_FILE" ]; then
        echo "No $APP_NAME server running ($PID_FILE is missing)."
        return 0
    fi

    PID=$(cat "$PID_FILE")
    if ! ps -p "$PID" > /dev/null 2>&1; then
        echo "No server running."
        rm -f "$PID_FILE"
        return 0
    fi

    echo -n "Stopping the $APP_NAME..."
    kill -TERM "$PID" && rm -f "$PID_FILE"
    echo "done."
}

# Function to check the app's status
do_status() {
    if [ ! -e "$PID_FILE" ]; then
        echo "No $APP_NAME server running ($PID_FILE is missing)."
        return 1
    fi

    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "$APP_NAME server is running."
    else
        echo "Server seems to have died."
        return 1
    fi
}

# Handle command line arguments
case "$1" in
    start)
        do_start
        ;;
    stop)
        do_stop
        ;;
    restart)
        do_stop
        sleep 1
        do_start
        ;;
    status)
        do_status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 2
        ;;
esac

exit $?
