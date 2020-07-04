#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/point-to-point-module.h"
#include "../helper/quic-network-simulator-helper.h"
#include "../helper/quic-point-to-point-helper.h"

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("ns3 simulator");

int main(int argc, char *argv[]) {
  std::string delay, bandwidth, queue, reordergap;
  CommandLine cmd;
  cmd.AddValue("delay", "delay of the p2p link", delay);
  cmd.AddValue("bandwidth", "bandwidth of the p2p link", bandwidth);
  cmd.AddValue("queue", "queue size of the p2p link (in packets)", queue);
  cmd.AddValue("reordergap", "Gap (amount packets) between each reordered packet", reordergap);
  cmd.Parse (argc, argv);

  NS_ABORT_MSG_IF(delay.length() == 0, "Missing parameter: delay");
  NS_ABORT_MSG_IF(bandwidth.length() == 0, "Missing parameter: bandwidth");
  NS_ABORT_MSG_IF(queue.length() == 0, "Missing parameter: queue");
  NS_ABORT_MSG_IF(reordergap.length() == 0, "Missing parameter: reordergap");

  QuicNetworkSimulatorHelper sim;

  // Stick in the point-to-point line between the sides.
  QuicPointToPointHelper p2p;
  p2p.SetDeviceAttribute("DataRate", StringValue(bandwidth));
  p2p.SetQueueSize(StringValue(queue + "p"));
  std::string tc_cmd = "tc qdisc add dev eth0 root netem delay " + delay + " reorder 100% gap " + reordergap;
  int status = system(tc_cmd.c_str());
  tc_cmd = "tc qdisc add dev eth1 root netem delay " + delay;
  status = system(tc_cmd.c_str());
  if (status)
    std::cout << "Error config tc" << std::endl;

  NetDeviceContainer devices = p2p.Install(sim.GetLeftNode(), sim.GetRightNode());
  Ipv4AddressHelper ipv4;
  ipv4.SetBase("193.167.50.0", "255.255.255.0");
  Ipv4InterfaceContainer interfaces = ipv4.Assign(devices);

  sim.Run(Seconds(36000));
}
