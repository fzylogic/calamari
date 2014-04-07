import getpass
import logging
import shutil
import tempfile
import time
import psutil
from itertools import chain
import yaml
from subprocess import Popen, PIPE
from utils import wait_until_true

from minion_sim.sim import MinionSim


log = logging.getLogger(__name__)


class CephControl(object):
    """
    Interface for tests to control one or more Ceph clusters under test.

    This can either be controlling the minion-sim, running unprivileged
    in a development environment, or it can be controlling a real life
    Ceph cluster.

    Some configuration arguments may be interpreted by a
    dev implementation as a "simulate this", while a real-cluster
    implementation might interpret them as "I require this state, skip
    the test if this cluster can't handle that".
    """

    def configure(self, server_count, cluster_count=1):
        """
        Tell me about the kind of system you would like.

        We will give you that system in a clean state or not at all:
        - Sometimes by setting it up for you here and now
        - Sometimes by cleaning up an existing cluster that's left from a previous test
        - Sometimes a clean cluster is already present for us
        - Sometimes we may not be able to give you the configuration you asked for
          (maybe you asked for more servers than we have servers) and have to
          throw you a test skip exception
        - Sometimes we may have a cluster that we can't clean up well enough
          to hand back to you, and have to throw you an error exception
        """
        raise NotImplementedError()

    def shutdown(self):
        """
        This cluster will not be used further by the test.

        If you created a cluster just for the test, tear it down here.  If the
        cluster was already up, just stop talking to it.
        """
        raise NotImplementedError()

    def mark_osd_in(self, fsid, osd_id, osd_in=True):
        raise NotImplementedError()

    def get_server_fqdns(self):
        raise NotImplementedError()

    def go_dark(self, fsid, dark=True, minion_id=None):
        """
        Create the condition where network connectivity between
        the calamari server and the ceph cluster is lost.
        """
        pass

    def get_fqdns(self, fsid):
        """
        Return all the FQDNs of machines with salt minion
        """
        raise NotImplementedError()


class EmbeddedCephControl(CephControl):
    """
    One or more simulated ceph clusters
    """
    def __init__(self):
        self._config_dirs = {}
        self._sims = {}

    def configure(self, server_count, cluster_count=1):
        osds_per_host = 4

        for i in range(0, cluster_count):
            domain = "cluster%d.com" % i
            config_dir = tempfile.mkdtemp()
            sim = MinionSim(config_dir, server_count, osds_per_host, port=8761 + i, domain=domain)
            fsid = sim.cluster.fsid
            self._config_dirs[fsid] = config_dir
            self._sims[fsid] = sim
            sim.start()

    def shutdown(self):
        log.info("%s.shutdown" % self.__class__.__name__)

        for sim in self._sims.values():
            sim.stop()
            sim.join()

        log.debug("lingering processes: %s" %
                  [p.name for p in psutil.process_iter() if p.username == getpass.getuser()])
        # Sleeps in tests suck... this one is here because the salt minion doesn't give us a nice way
        # to ensure that when we shut it down, subprocesses are complete before it returns, and even
        # so we can't be sure that messages from a dead minion aren't still winding their way
        # to cthulhu after this point.  So we fudge it.
        time.sleep(5)

        for config_dir in self._config_dirs.values():
            shutil.rmtree(config_dir)

    def get_server_fqdns(self):
        return list(chain(*[s.get_minion_fqdns() for s in self._sims.values()]))

    def mark_osd_in(self, fsid, osd_id, osd_in=True):
        self._sims[fsid].cluster.set_osd_state(osd_id, osd_in=1 if osd_in else 0)

    def go_dark(self, fsid, dark=True, minion_id=None):
        if minion_id:
            if dark:
                self._sims[fsid].halt_minion(minion_id)
            else:
                self._sims[fsid].start_minion(minion_id)
        else:
            if dark:
                self._sims[fsid].halt_minions()
            else:
                self._sims[fsid].start_minions()

        # Sleeps in tests suck... this one is here because the salt minion doesn't give us a nice way
        # to ensure that when we shut it down, subprocesses are complete before it returns, and even
        # so we can't be sure that messages from a dead minion aren't still winding their way
        # to cthulhu after this point.  So we fudge it.
        time.sleep(5)

    def get_fqdns(self, fsid):
        return self._sims[fsid].get_minion_fqdns()

    def get_service_fqdns(self, fsid, service_type):
        return self._sims[fsid].cluster.get_service_fqdns(service_type)


class ExternalCephControl(CephControl):
    """
    This is the code that talks to a cluster. It is currently dependent on teuthology
    """

    def __init__(self):
        # TODO parse the real config
        self.config = yaml.load("""
ubuntu@mira002.front.sepia.ceph.com:
- mon.0
- osd.0
- client.0
ubuntu@mira028.front.sepia.ceph.com:
- mon.1
- osd.1
ubuntu@mira043.front.sepia.ceph.com:
- mon.2
- osd.3
""")
        # Here we will want to parse the config.yaml(s)


    def configure(self, server_count, cluster_count=1):

        # GRUMBLE: Teuthology doesn't seem to provide any correlation between role and target, even in the
        # YAML it produces with --archive

        # GRUMBLE: All of the example YAMLs have roles: sections that name things like [client|mon|osd].[0-9]+
        # this is misleading because those aren't ids

        # I hope you only wanted three, because I ain't buying
        # any more servers...
        assert server_count == 3
        assert cluster_count == 1
        fsid = 12345

        # Ensure all OSDs are initially up: assertion per #7813
        self._wait_for_state(fsid, "ceph osd stat", self._check_osd_up_and_in)

        # Ensure there are initially no pools but the default ones. assertion per #7813
        self._wait_for_state(fsid, "ceph osd lspools", self._check_default_pools_only)

        # wait till all PGs are active and clean assertion per #7813
        self._wait_for_state(fsid, "ceph pg stat", self._check_pgs_active_and_clean)

        # bootstrap salt minions on cluster
        # TODO is the right place for it

        # set config dirs
        # set sims

    def get_server_fqdns(self):
        return [target.split('@')[1] for target in self.config.iterkeys()]

    def get_service_fqdns(self, fsid, service_type):
        # I run OSDs and mons in the same places (on all three servers)
        return self.get_server_fqdns()

    def shutdown(self):
        pass

    def get_fqdns(self, fsid):
        # TODO when we support multiple cluster change this
        return self.get_server_fqdns()

    def go_dark(self, fsid, dark=True, minion_id=None):
        pass

    def _check_default_pools_only(self, output):
        if output:
            return output.strip() == '0 data,1 metadata,2 rbd,'
        return False

    def _wait_for_state(self, fsid, command, state):
        log.info('Waiting for {state} on cluster {fsid}'.format(state=state, fsid=fsid))
        check = 'ssh {node} "{command}"'.format(node=self._get_admin_node(fsid=fsid), command=command)
        output = Popen(check, shell=True, stdout=PIPE).communicate()[0]
        wait_until_true(lambda: state(output))

    def _check_pgs_active_and_clean(self, output):
        if output:
            try:
                _, total_stat, pg_stat, _ = output.replace(';', ':').split(':')
                return 'active+clean' == pg_stat.split()[1] and total_stat.split()[0] == pg_stat.split()[0]
            except ValueError:
                log.warning('ceph pg stat format may have changed')

        return False

    def _check_osd_up_and_in(self, output):
        if output:
            try:
                _, total, osd_up, osd_in = [x.split()[0] for x in output.replace(',', ':').split(':')]
                return total == osd_in == osd_up
            except ValueError:
                log.warning('ceph osd stat format may have changed')

        return False

    def _bootstrap(self, target, fqdn):
        command = '''ssh {target} "wget -O - https://raw.github.com/saltstack/salt-bootstrap/develop/bootstrap-salt.sh |\
         sudo sh ; sudo sed -i 's/^[#]*master:.*$/master: {fqdn}/' /etc/salt/minion && sudo service salt-minion restart"'''.format(target=target, fqdn=fqdn)
        output = Popen(command, shell=True, stdout=PIPE).communicate()[0]
        log.info(output)

    def _get_admin_node(self, fsid):
        for target, roles in self.config.iteritems():
            if 'client.0' in roles:
                return target

    def mark_osd_in(self, fsid, osd_id, osd_in=True):

        command = 'in'
        if not osd_in:
            command = 'out'

        # TODO figure out what server to target
        proc = Popen('ssh {admin_node} "ceph osd {command} {id}"'.format(admin_node=self._get_admin_node(fsid), command=command, id=int(osd_id)), shell=True, stderr=PIPE, stdout=PIPE)

        print proc.communicate()


if __name__ == "__main__":
    externalctl = ExternalCephControl()
    assert isinstance(externalctl.config, dict)
    #externalctl.configure(3)
    externalctl._bootstrap("ubuntu@mira002.front.sepia.ceph.com", '10.99.118.150')