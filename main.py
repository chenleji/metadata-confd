import requests
import time
import json
import requests_unixsocket
from docker import Client

PATH_FIP_JSON_DB = "/var/run/wise2c_fip_db.json"
INTERVAL_SECOND = 2
FLOATING_IP_LABEL = "io.rancher.container.floating.ip"

PATH_NETWORK_DRIVER_SOCK = "unix://%2Fvar%2Frun%2Fwise2c_fip_worker.sock"
URL_NETWORK_DRIVER_JOIN = "http+%s/NetworkDriver/Join" % PATH_NETWORK_DRIVER_SOCK
URL_NETWORK_DRIVER_LEAVE = "http+%s/NetworkDriver/Leave" % PATH_NETWORK_DRIVER_SOCK


class MetadataConfd:
    PREFIX = "http://rancher-metadata/2015-07-25"
    URL_SELF_HOST_UUID = PREFIX + "/self/host/uuid"
    URL_SELF_HOST_IP = PREFIX + "/self/host/agent_ip"
    URL_CONTAINERS = PREFIX + "/containers"
    URL_CONTAINER_HOST_UUID = PREFIX + "/containers/%s/host_uuid"
    URL_CONTAINER_UUID = PREFIX + "/containers/%s/uuid"
    URL_CONTAINER_LABELS = PREFIX + "/containers/%s/labels"
    URL_CONTAINER_IP = PREFIX + "/containers/%s/labels/io.rancher.container.ip"
    URL_CONTAINER_FLOATING_IP = PREFIX + "/containers/%s/labels/io.rancher.container.floating.ip"

    def __init__(self, floating_ip_label, containers_origin):
        self.floating_ip_label = floating_ip_label
        self.my_host_uuid = self.get_self_host_uuid()
        self.my_host_ip = self.get_self_host_ip()
        self.containers_origin = containers_origin

    @staticmethod
    def get_value(url):
        try:
            r = requests.get(url)
        except Exception as e:
            print "##### Exception:get_value #####"
            print e
            return None

        if r.status_code != requests.codes.ok:
            return None
        return r.text

    def get_self_host_uuid(self):
        resp = self.get_value(self.URL_SELF_HOST_UUID)
        return resp

    def get_self_host_ip(self):
        resp = self.get_value(self.URL_SELF_HOST_IP)
        return resp

    def get_containers(self):
        resp = self.get_value(self.URL_CONTAINERS)
        '''' ## format ##
        0=Network+Agent\n1=jenkins2-agent_swarm-clients_2\n2=jenkins2-agent_swarm-clients_3\n
        '''
        items = resp.split('\n')
        containers = dict()
        for i in items:
            kv = i.split('=')
            if len(kv) == 2:
                containers[kv[0]] = kv[1]
        return containers

    def get_host_uuid_by_container(self, container_name):
        resp = self.get_value(self.URL_CONTAINER_HOST_UUID % container_name)
        return resp

    def get_container_uuid_by_name(self, container_name):
        resp = self.get_value(self.URL_CONTAINER_UUID % container_name)
        return resp

    def get_container_ip_by_name(self, container_name):
        resp = self.get_value(self.URL_CONTAINER_IP % container_name)
        return resp

    def get_container_floating_ip_by_name(self, container_name):
        resp = self.get_value(self.URL_CONTAINER_LABELS % container_name)
        items = resp.split('\n')
        if self.floating_ip_label not in items:
            return None
        else:
            resp = self.get_value(self.URL_CONTAINER_FLOATING_IP % container_name)
            return resp

    def get_containers_on_my_host(self):
        containers_on_my_host = dict()
        containers = self.get_containers()
        for k in containers:
            name = containers[k]
            if self.get_host_uuid_by_container(name) == self.my_host_uuid:
                uuid = self.get_container_uuid_by_name(name)
                ip = self.get_container_ip_by_name(name)
                floating_ip = self.get_container_floating_ip_by_name(name)
                if (uuid is None) or (ip is None) or (floating_ip is None):
                    continue
                containers_on_my_host[name] = {
                    "uuid": uuid,
                    "name": name,
                    "managed_ip": ip,
                    "floating_ip": floating_ip,
                }
        return containers_on_my_host

    def get_containers_need_to_update(self):
        containers_added = dict()
        containers_removed = dict()
        containers_updated = dict()
        containers_with_floating_ip = self.get_containers_on_my_host()

        for k in self.containers_origin:
            if k not in containers_with_floating_ip:
                containers_removed[k] = self.containers_origin[k]
        for k in containers_with_floating_ip:
            if k not in self.containers_origin:
                containers_added[k] = containers_with_floating_ip[k]
        for k in self.containers_origin:
            if containers_with_floating_ip.has_key(k):
                if self.containers_origin[k]['ip'] != containers_with_floating_ip[k]['ip']:
                    containers_updated[k] = containers_with_floating_ip[k]
        self.containers_origin = containers_with_floating_ip

        return containers_added, containers_removed, containers_updated


def call_fip_worker_join(fip, lip):
    requests_unixsocket.monkeypatch()
    payload = {'FloatingIP': fip, 'LocalIP': lip}
    r = requests.post(URL_NETWORK_DRIVER_JOIN, data=json.dumps(payload))
    if r.status_code != 200:
        return False
    return True


def call_fip_worker_leave(fip, lip):
    requests_unixsocket.monkeypatch()
    payload = {'FloatingIP': fip, 'LocalIP': lip}
    r = requests.post(URL_NETWORK_DRIVER_LEAVE, data=json.dumps(payload))
    if r.status_code != 200:
        return False
    return True


def main():
    docker_client = Client(base_url='unix://var/run/docker.sock')
    containers_with_fip = dict()

    with open(PATH_FIP_JSON_DB, 'w+') as fp:
        try:
            containers_with_fip = json.load(fp)
        except Exception as e:
            print "#### load json db failed! ####"
            print e

    md_confd = MetadataConfd(FLOATING_IP_LABEL, containers_with_fip)

    '''
    wise2c_networks = dict()

    # find out the 'wise2c' network in system
    networks = docker_client.networks()
    for i in networks:
        if i['Driver'] != 'wise2c-bridge':
            continue
        else:
            wise2c_networks.update(i)
            break

    # there is no 'wise2c' network in system => create it.
    if wise2c_networks == {}:
        r = docker_client.create_network(name='wise2c', driver='wise2c-bridge')
        wise2c_networks.update(r)
    '''

    while True:
        try:
            containers_added, containers_removed, containers_updated = \
                md_confd.get_containers_need_to_update()
        except Exception as e:
            print "##### Exception:get_containers_need_to_update ######"
            print e
            time.sleep(INTERVAL_SECOND)
            continue

        # process removed containers with floating ip
        for name in containers_removed:
            print "###### removed containers ######"
            fip = containers_with_fip[name]['floating_ip']
            lip = containers_with_fip[name]['local_ip']
            if not call_fip_worker_leave(fip, lip):
                print "Call call_fip_worker_leave failed!"

            containers_with_fip.pop(name)

            '''
            try:
                docker_client.disconnect_container_from_network("r-"+name, wise2c_networks['Id'])
            except Exception as e:
                print e
            '''

        # process new added containers with floating ip
        for name in containers_added:
            print "###### added containers ######"
            print containers_added[name]
            containers = docker_client.containers(filters={'name': 'r-'+name})
            if not containers[0]['NetworkSettings']['Networks'].has_key('bridge'):
                print "Container does not connect to default bridge!"
                break
            if not containers[0]['NetworkSettings']['Networks']['bridge'].has_key('IPAddress'):
                print "Container have no IP on bridge!"
                break

            containers_added[name]['local_ip'] = \
                containers[0]['NetworkSettings']['Networks']['bridge']['IPAddress']
            if not call_fip_worker_join(containers_added[name]['floating_ip'],
                                        containers_added[name]['local_ip']):
                print "Call call_fip_worker_join failed!"

            containers_with_fip[name] = containers_added[name]

            # 1. send msg to add vip on default gw interface
            # 2. update DNAT to container bridge_ip
            '''
            try:
                docker_client.connect_container_to_network("r-"+name, wise2c_networks['Id'])
            except Exception as e:
                print e
            '''

        # process containers which updated ip address
        '''
        for name in containers_updated:
            print "###### updated containers ######"
            print containers_updated[name]
            containers = docker_client.containers(filters={'name': 'r-'+name})
            if not containers[0]['NetworkSettings']['Networks'].has_key('bridge'):
                print "Container does not connect to default bridge!"
                break
            if not containers[0]['NetworkSettings']['Networks']['bridge'].has_key('IPAddress'):
                print "Container have no IP on bridge!"
                break

            lip = containers[0]['NetworkSettings']['Networks']['bridge']['IPAddress']
            if not call_fip_worker_leave(containers_updated[name]['floating_ip'], lip):
                print "Call call_fip_worker_leave failed!"

            try:
                docker_client.disconnect_container_from_network("r-"+name, wise2c_networks['Id'])
                time.sleep(2)
                docker_client.connect_container_to_network("r-"+name, wise2c_networks['Id'])
            except Exception as e:
                print e
        '''
        with open(PATH_FIP_JSON_DB, 'w+') as fp:
            json.dump(containers_with_fip, fp)

        time.sleep(INTERVAL_SECOND)


if __name__ == '__main__':
    main()
