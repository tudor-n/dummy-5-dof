#!/usr/bin/env bash
# Build the ESP32 firmware (src/main.c) with ESP-IDF in Docker and flash it. No PlatformIO needed.
#
#   ./flash.sh                build, then flash (finds /dev/ttyUSB* or /dev/ttyACM* itself)
#   ./flash.sh /dev/ttyUSB1   flash to this port
#   ./flash.sh --build        build only
#   ./flash.sh --monitor      flash, then watch the serial output (Ctrl+] quits)
#
# Close DUMMY first: it holds the port. Needs Docker. The first run downloads the image (a few GB);
# the build is cached in ~/.cache/dummy-firmware, so later runs take seconds.
set -euo pipefail

IDF_IMAGE=espressif/idf:v5.5.3   # the ESP-IDF the firmware was built with (it's in the ESP32's boot banner)
here=$(cd "$(dirname "$0")" && pwd)
work=${XDG_CACHE_HOME:-$HOME/.cache}/dummy-firmware
mkdir -p "$work"

build_only=0; monitor=0; port=""
for a in "$@"; do
  case $a in
    --build) build_only=1 ;;
    --monitor) monitor=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) port=$a ;;
  esac
done

dev_args=()
if [ $build_only = 0 ]; then
  if [ -z "$port" ]; then
    port=$(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null | head -1 || true)
    [ -n "$port" ] || { echo "No ESP32 port found (/dev/ttyUSB*, /dev/ttyACM*). Plug it in, or pass the port."; exit 1; }
  fi
  [ -e "$port" ] || { echo "$port doesn't exist."; exit 1; }
  if command -v fuser >/dev/null && fuser "$port" >/dev/null 2>&1; then
    echo "$port is in use (DUMMY, or a serial monitor?). Close it first."; exit 1
  fi
  dev_args=(--device "$port:$port" --group-add "$(stat -c %g "$port")")
fi

steps="build"
[ $build_only = 1 ] || steps="build flash"
[ $monitor = 1 ] && steps="$steps monitor"

tty_args=()
[ -t 0 ] && tty_args=(-it)

echo "ESP-IDF ${IDF_IMAGE#*:}: $steps${port:+ on $port}"
# The repo is mounted read-only and copied into the cache, so the build never writes into the
# checkout (sdkconfig.esp32dev stays as committed).
docker run --rm "${tty_args[@]}" -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$here:/repo:ro" -v "$work:/work" "${dev_args[@]}" "$IDF_IMAGE" bash -c '
    set -e
    mkdir -p /work/proj
    cp /repo/CMakeLists.txt /work/proj/
    # src/ becomes the "main" component, as PlatformIO builds it (main may use every IDF component)
    rm -rf /work/proj/src /work/proj/main && mkdir /work/proj/main
    cp /repo/src/*.c /repo/src/*.h /work/proj/main/ 2>/dev/null || true
    cat > /work/proj/main/CMakeLists.txt <<EOF
file(GLOB srcs "\${CMAKE_CURRENT_LIST_DIR}/*.c")
idf_component_register(SRCS \${srcs})
EOF
    cmp -s /repo/sdkconfig.esp32dev /work/proj/sdkconfig || cp /repo/sdkconfig.esp32dev /work/proj/sdkconfig
    cd /work/proj
    idf.py -B build '"${port:+-p $port -b 460800}"' '"$steps"'
  '
