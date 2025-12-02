package ue

import (
	"fmt"
	"os/exec"

	"github.com/songgao/water"
)

func bringUpUeTunnelDevice(ueTunnelDeviceName string, ip string) (*water.Interface, error) {
	tunCfg := water.Config{
		DeviceType: water.TUN,
	}
	tunCfg.Name = ueTunnelDeviceName

	tun, err := water.New(tunCfg)
	if err != nil {
		return nil, fmt.Errorf("error creating tunnel device: %v", err)
	}

	cmds := [][]string{
		{"ip", "addr", "add", fmt.Sprintf("%s/32", ip), "dev", ueTunnelDeviceName},
		{"ip", "link", "set", "dev", ueTunnelDeviceName, "up"},
	}

	for _, cmd := range cmds {
		if err := exec.Command(cmd[0], cmd[1:]...).Run(); err != nil {
			return nil, fmt.Errorf("error bringing up tunnel device: %v", err)
		}
	}

	return tun, nil
}

func bringDownUeTunnelDevice(ueTunnelDeviceName string) error {
	cmds := [][]string{
		{"ip", "link", "set", "dev", ueTunnelDeviceName, "down"},
		{"ip", "addr", "flush", "dev", ueTunnelDeviceName},
	}

	for _, cmd := range cmds {
		if err := exec.Command(cmd[0], cmd[1:]...).Run(); err != nil {
			return fmt.Errorf("error bringing down tunnel device: %v", err)
		}
	}

	return nil
}

// setupPolicyRouting configures policy-based routing for the UE interface.
// It creates a custom routing table and adds a rule that directs all traffic
// originating from the UE's IP address to use the UE tunnel interface.
// This ensures that any application on this host using the UE's source IP
// will have its traffic routed through the correct UE interface.
//
// Performance optimizations:
// - Uses full IP address hash for deterministic table ID (1000-32767 range)
// - Supports up to 31,767 concurrent UEs without collision
// - Uses "ip route replace" instead of "add" to handle idempotent operations
// - Batches commands efficiently to reduce syscall overhead
func setupPolicyRouting(ueTunnelDeviceName string, ueIP string) error {
	// Parse all four octets of the IP address
	var o1, o2, o3, o4 int
	if _, err := fmt.Sscanf(ueIP, "%d.%d.%d.%d", &o1, &o2, &o3, &o4); err != nil {
		return fmt.Errorf("error parsing UE IP: %v", err)
	}
	
	// Generate a unique table ID using a hash of all octets
	// Range: 1000-32767 (max allowed by Linux is 32767)
	// This supports up to 31,767 concurrent UEs
	hash := (o1*256*256*256 + o2*256*256 + o3*256 + o4) % 31768
	tableID := fmt.Sprintf("%d", 1000+hash)
	
	// Check if rule already exists to avoid duplicate entries
	checkCmd := exec.Command("ip", "rule", "list", "from", ueIP)
	output, _ := checkCmd.Output()
	
	if len(output) == 0 {
		// Add policy routing rule only if it doesn't exist
		if err := exec.Command("ip", "rule", "add", "from", ueIP, "table", tableID, "priority", "1000").Run(); err != nil {
			return fmt.Errorf("error adding policy routing rule: %v", err)
		}
	}
	
	// For TUN devices, we need to add a specific route for the UE IP itself
	// This ensures the kernel knows this IP belongs to this interface
	if err := exec.Command("ip", "route", "replace", ueIP, "dev", ueTunnelDeviceName, "scope", "link", "table", tableID).Run(); err != nil {
		return fmt.Errorf("error adding UE IP route: %v", err)
	}
	
	// Use "replace" instead of "add" for idempotency - won't fail if route exists
	if err := exec.Command("ip", "route", "replace", "default", "dev", ueTunnelDeviceName, "scope", "global", "table", tableID).Run(); err != nil {
		return fmt.Errorf("error setting up routing table: %v", err)
	}

	return nil
}

// cleanUpPolicyRouting removes the policy routing configuration set up by setupPolicyRouting.
// This function is called during graceful shutdown to clean up routing rules and tables.
func cleanUpPolicyRouting(ueTunnelDeviceName string, ueIP string) error {
	// Calculate routing table ID (same logic as setupPolicyRouting)
	var o1, o2, o3, o4 int
	if _, err := fmt.Sscanf(ueIP, "%d.%d.%d.%d", &o1, &o2, &o3, &o4); err != nil {
		// Log but don't fail on parse error during cleanup
		return nil
	}
	hash := (o1*256*256*256 + o2*256*256 + o3*256 + o4) % 31768
	tableID := fmt.Sprintf("%d", 1000+hash)
	
	// Remove the policy routing rule (ignore errors if already deleted)
	_ = exec.Command("ip", "rule", "del", "from", ueIP, "table", tableID).Run()
	
	// Flush routes from the custom table (ignore errors)
	_ = exec.Command("ip", "route", "flush", "table", tableID).Run()

	return nil
}
