import copy, os, random, shutil, subprocess, string, logging, sys, tempfile, argparse, re
from typing import List
from termcolor import colored
from enum import Enum
import prettytable

import testcases
from testcases import TESTCASES
from implementations import IMPLEMENTATIONS

def get_args():
  parser = argparse.ArgumentParser()
  parser.add_argument('-d', '--debug', action='store_const',
                      const=True, default=False,
                      help='turn on debug logs')
  parser.add_argument("-s", "--server", help="server implementations (comma-separated)")
  parser.add_argument("-c", "--client", help="client implementations (comma-separated)")
  parser.add_argument("-t", "--test", help="test cases (comma-separatated)")
  parser.add_argument("-r", "--replace", help="replace path of implementation. Example: -r myquicimpl=dockertagname")
  return parser.parse_args()

def random_string(length: int):
  """ Generate a random string of fixed length """
  letters = string.ascii_lowercase
  return ''.join(random.choice(letters) for i in range(length))

class TestResult(Enum):
  SUCCEEDED = 1
  FAILED = 2
  UNSUPPORTED = 3

class LogFileFormatter(logging.Formatter):
  def format(self, record):
    msg = super(LogFileFormatter, self).format(record)
    # remove color control characters
    return re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]').sub('', msg)

class InteropRunner:
  results = {}
  compliant = {}
  _servers = {}
  _clients = {}
  _tests = []

  def __init__(self, servers: dict, clients: dict, tests: List[testcases.TestCase]):
    self._tests = tests
    self._servers = servers
    self._clients = clients
    for server in servers:
      self.results[server] = {}
      for client in clients:
        self.results[server][client] = {
          TestResult.SUCCEEDED: [],
          TestResult.FAILED: [],
          TestResult.UNSUPPORTED: [],
        }

  def _is_unsupported(self, lines: List[str]) -> bool:
    return any("exited with code 127" in str(l) for l in lines) or any("exit status 127" in str(l) for l in lines)

  def _check_impl_is_compliant(self, name: str) -> bool:
    """ check if an implementation return UNSUPPORTED for unknown test cases """
    if name in self.compliant:
      logging.debug("%s already tested for compliance: %s", name, str(self.compliant))
      return self.compliant[name]

    sim_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_sim_")
    client_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_client_")

    # check that the client is capable of returning UNSUPPORTED
    logging.debug("Checking compliance of %s client", name)
    cmd = (
        "TESTCASE=" + random_string(6) + " "
        "SERVER_LOGS=/dev/null "
        "CLIENT_LOGS=" + client_log_dir.name + " " 
        "SIM_LOGS=" + sim_log_dir.name + " "
        "WWW=/dev/null DOWNLOADS=/dev/null "
        "SCENARIO=\"simple-p2p --delay=15ms --bandwidth=10Mbps --queue=25\" "
        "CLIENT=" + IMPLEMENTATIONS[name] + " "
        "docker-compose -f ../docker-compose.yml -f interop.yml up --timeout 0 --abort-on-container-exit sim client"
      )
    output = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if not self._is_unsupported(output.stdout.splitlines()):
      logging.error("%s client not compliant.", name)
      logging.debug("%s", output.stdout.decode('utf-8'))
      self.compliant[name] = False
      return False
    logging.debug("%s client compliant.", name)

    # check that the server is capable of returning UNSUPPORTED
    logging.debug("Checking compliance of %s server", name)
    sim_log_dir.cleanup()
    sim_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_sim_")
    server_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_server_")
    cmd = (
        "TESTCASE=" + random_string(6) + " "
        "SERVER_LOGS=" + server_log_dir.name + " "
        "CLIENT_LOGS=/dev/null "
        "SIM_LOGS=" + sim_log_dir.name + " "
        "WWW=/dev/null DOWNLOADS=/dev/null "
        "SERVER=" + IMPLEMENTATIONS[name] + " "
        "docker-compose -f ../docker-compose.yml -f interop.yml up server"
      )
    output = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if not self._is_unsupported(output.stdout.splitlines()):
      logging.error("%s server not compliant.", name)
      logging.debug("%s", output.stdout.decode('utf-8'))
      self.compliant[name] = False
      return False
    logging.info("%s server compliant.", name)
    
    # remember compliance test outcome
    self.compliant[name] = True
    return True


  def _print_results(self):
    """print the interop table"""
    def get_letters(testcases):
      if len(testcases) == 0:
        return "-"
      return "".join([ test.abbreviation() for test in testcases ])
      
    t = prettytable.PrettyTable()
    t.hrules = prettytable.ALL
    t.vrules = prettytable.ALL
    t.field_names = [ "" ] + [ name for name in self._servers ]
    for client in self._clients:
      row = [ client ]
      for server in self._servers:
        cell = self.results[server][client]
        res = colored(get_letters(cell[TestResult.SUCCEEDED]), "green") + "\n"
        res += colored(get_letters(cell[TestResult.UNSUPPORTED]), "yellow") + "\n"
        res += colored(get_letters(cell[TestResult.FAILED]), "red")
        row += [ res ]
      t.add_row(row)
    print(t)

  def _run_testcase(self, server: str, client: str, testcase: testcases.TestCase) -> TestResult:
    print("Server: " + server + ". Client: " + client + ". Running test case: " + str(testcase))
    server_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_server_")
    client_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_client_")
    sim_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_sim_")
    log_file = tempfile.NamedTemporaryFile(dir="/tmp", prefix="output_log_")
    log_handler = logging.FileHandler(log_file.name)
    log_handler.setLevel(logging.DEBUG)

    formatter = LogFileFormatter('%(asctime)s %(message)s')
    log_handler.setFormatter(formatter)
    logging.getLogger().addHandler(log_handler)

    reqs = " ".join(["https://server:443/" + p for p in testcase.get_paths()])
    logging.debug("Requests: %s", reqs)
    cmd = (
      "TESTCASE=" + str(testcase) + " "
      "WWW=" + testcase.www_dir() + " "
      "DOWNLOADS=" + testcase.download_dir() + " "
      "SERVER_LOGS=" + server_log_dir.name + " "
      "CLIENT_LOGS=" + client_log_dir.name + " "
      "SIM_LOGS=" + sim_log_dir.name + " "
      "SCENARIO=\"simple-p2p --delay=15ms --bandwidth=10Mbps --queue=25\" "
      "CLIENT=" + IMPLEMENTATIONS[client] + " "
      "SERVER=" + IMPLEMENTATIONS[server] + " "
      "REQUESTS=\"" + reqs + "\" "
      "docker-compose -f ../docker-compose.yml -f interop.yml up --abort-on-container-exit --timeout 1"
    )
    output = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    logging.debug("%s", output.stdout.decode('utf-8'))

    lines = output.stdout.splitlines()

    status = TestResult.FAILED
    if self._is_unsupported(lines):
      status = TestResult.UNSUPPORTED
    elif any("client exited with code 0" in str(l) for l in lines):
      if testcase.check():
        status = TestResult.SUCCEEDED

    # save logs
    logging.getLogger().removeHandler(log_handler)
    log_handler.close()
    if status == TestResult.FAILED or status == TestResult.SUCCEEDED:
      log_dir = "logs/" + server + "_" + client + "/" + str(testcase)
      shutil.copytree(server_log_dir.name, log_dir + "/server")
      shutil.copytree(client_log_dir.name, log_dir + "/client")
      shutil.copytree(sim_log_dir.name, log_dir + "/sim")
      shutil.copyfile(log_file.name, log_dir + "/output.txt")

    testcase.cleanup()
    server_log_dir.cleanup()
    client_log_dir.cleanup()
    sim_log_dir.cleanup()
    return status

  def run(self):
    """run the interop test suite and output the table"""

    # clear the logs directory
    if os.path.exists("logs/"):
      shutil.rmtree("logs/")
    
    for server in self._servers:
      for client in self._clients:
        logging.info("Running with server %s (%s) and client %s (%s)", server, self._servers[server], client, self._clients[client])
        if not (self._check_impl_is_compliant(server) and self._check_impl_is_compliant(client)):
          logging.info("Not compliant, skipping")
          continue

        # run the test cases
        for testcase in self._tests:
          status = self._run_testcase(server, client, testcase)
          self.results[server][client][status] += [ testcase ]

    self._print_results()


logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
console = logging.StreamHandler(stream=sys.stderr)
if get_args().debug:
  console.setLevel(logging.DEBUG)
else:
  console.setLevel(logging.INFO)
logger.addHandler(console)

implementations = copy.deepcopy(IMPLEMENTATIONS)
replace_arg = get_args().replace
if replace_arg:
  for s in replace_arg.split(","):
    pair = s.split("=")
    if len(pair) != 2:
      sys.exit("Invalid format for replace")
    name, image = pair[0], pair[1]
    if name not in IMPLEMENTATIONS:
      sys.exit("Implementation " + name + " not found.")
    implementations[name] = image

def get_impls(arg) -> dict:
  if not arg:
    return implementations
  impls = {}
  for s in arg.split(","):
    if s not in implementations:
      sys.exit("Implementation " + s + " not found.")
    impls[s] = implementations[s]
  return impls

def get_tests(arg) -> List[testcases.TestCase]:
  if not arg:
    return TESTCASES
  tests = []
  for t in arg.split(","):
    if t not in [ str(n) for n in TESTCASES ]:
      sys.exit("Test case " + t + " not found.")
    tests += [ n for n in TESTCASES if str(n)==t ]
  return tests 
    
InteropRunner(
  servers=get_impls(get_args().server), 
  clients=get_impls(get_args().client),
  tests=get_tests(get_args().test),
).run()
