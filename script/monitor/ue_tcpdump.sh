#!/bin/bash

# UE TCPdump 封包擷取腳本
# 用途: 擷取指定 UE 的網路封包並儲存至 PCAP 目錄

# 顏色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 預設值
UE_IP=""
INTERFACE="any"
PORT=""
FILTER=""

# 使用說明
usage() {
    echo "使用方法: $0 -i <UE_IP> [-p <PORT>] [-I <INTERFACE>] [-f <FILTER>]"
    echo ""
    echo "選項:"
    echo "  -i <UE_IP>       必填: UE 的 IP 位址 (例如: 127.0.0.8)"
    echo "  -p <PORT>        選填: 指定埠號 (例如: 8805)"
    echo "  -I <INTERFACE>   選填: 網路介面 (預設: any)"
    echo "  -f <FILTER>      選填: 額外的 tcpdump 過濾條件"
    echo ""
    echo "範例:"
    echo "  $0 -i 127.0.0.8"
    echo "  $0 -i 127.0.0.8 -p 8805"
    echo "  $0 -i 10.60.0.1 -I ueTun"
    echo "  $0 -i 127.0.0.8 -f \"tcp\""
    exit 1
}

# 檢查是否以 root 權限執行
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}錯誤: 請使用 sudo 執行此腳本${NC}"
    exit 1
fi

# 解析參數
while getopts "i:p:I:f:h" opt; do
    case $opt in
        i)
            UE_IP="$OPTARG"
            ;;
        p)
            PORT="$OPTARG"
            ;;
        I)
            INTERFACE="$OPTARG"
            ;;
        f)
            FILTER="$OPTARG"
            ;;
        h)
            usage
            ;;
        \?)
            echo -e "${RED}無效的選項: -$OPTARG${NC}" >&2
            usage
            ;;
    esac
done

# 檢查必填參數
if [ -z "$UE_IP" ]; then
    echo -e "${RED}錯誤: 必須指定 UE IP 位址${NC}"
    usage
fi

# 建立 PCAP 目錄結構
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PCAP_BASE_DIR="$SCRIPT_DIR/PCAP"
TIMESTAMP=$(date +'%Y%m%d_%H%M%S')
PCAP_DIR="$PCAP_BASE_DIR/$TIMESTAMP"

# 創建目錄
mkdir -p "$PCAP_DIR"
if [ $? -ne 0 ]; then
    echo -e "${RED}錯誤: 無法創建目錄 $PCAP_DIR${NC}"
    exit 1
fi

# 建立過濾條件
TCPDUMP_FILTER="host $UE_IP"

if [ -n "$PORT" ]; then
    TCPDUMP_FILTER="$TCPDUMP_FILTER and port $PORT"
fi

if [ -n "$FILTER" ]; then
    TCPDUMP_FILTER="$TCPDUMP_FILTER and $FILTER"
fi

# 生成檔案名稱
FILENAME="UE_${UE_IP//./_}"
if [ -n "$PORT" ]; then
    FILENAME="${FILENAME}_port${PORT}"
fi
FILENAME="${FILENAME}_${TIMESTAMP}.pcap"

PCAP_FILE="$PCAP_DIR/$FILENAME"

# 顯示資訊
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}UE TCPdump 封包擷取${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "UE IP:        ${YELLOW}$UE_IP${NC}"
echo -e "介面:         ${YELLOW}$INTERFACE${NC}"
if [ -n "$PORT" ]; then
    echo -e "埠號:         ${YELLOW}$PORT${NC}"
fi
echo -e "過濾條件:     ${YELLOW}$TCPDUMP_FILTER${NC}"
echo -e "輸出檔案:     ${YELLOW}$PCAP_FILE${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${YELLOW}開始擷取封包... (按 Ctrl+C 停止)${NC}"
echo ""

# 執行 tcpdump
tcpdump -i "$INTERFACE" "$TCPDUMP_FILTER" -w "$PCAP_FILE"

# 擷取結束後顯示資訊
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}封包擷取完成${NC}"
echo -e "${GREEN}========================================${NC}"

# 顯示檔案資訊
if [ -f "$PCAP_FILE" ]; then
    FILE_SIZE=$(du -h "$PCAP_FILE" | cut -f1)
    echo -e "檔案位置: ${YELLOW}$PCAP_FILE${NC}"
    echo -e "檔案大小: ${YELLOW}$FILE_SIZE${NC}"
    
    # 嘗試顯示封包數量
    if command -v capinfos &> /dev/null; then
        PACKET_COUNT=$(capinfos -c "$PCAP_FILE" 2>/dev/null | grep "Number of packets" | awk '{print $4, $5}')
        if [ -n "$PACKET_COUNT" ]; then
            echo -e "封包數量: ${YELLOW}$PACKET_COUNT${NC}"
        fi
    fi
else
    echo -e "${RED}警告: 找不到輸出檔案${NC}"
fi

echo -e "${GREEN}========================================${NC}"
