from cassandra.cluster import DefaultConnection, Session
from cassandra.connection import locally_supported_compressions
from cassandra.protocol import ProxiedMessage


compressor, decompressor = locally_supported_compressions['snappy']


class ProxyConnection(DefaultConnection):

    compressor = staticmethod(compressor)
    decompressor = staticmethod(decompressor)

    def __init__(self, host='127.0.0.1', port=9042, *args, **kwargs):
        self.proxy_cluster = kwargs.pop('proxy_cluster')
        return super().__init__(host, port, *args, **kwargs)

    def _send_options_message(self):
        # options message is not necessary for proxy - it's handled by the
        # proxy <-> scylla connection.
        self.connected_event.set()

    def close(self):
        super().close()

        try:
            self._connect_socket()
        except ConnectionError:
            # if it was closed by the server, and immediate reconnection fails,
            # then we want to try to reconnect later, which is scheduled
            # by on_down:
            self.proxy_cluster.on_down(
                self.proxy_cluster.proxy_host,
                is_host_addition=False,
                expect_host_to_be_down=True,
            )
        # otherwise it was probably intentional disconnection

    def send_msg(self, msg, *args, **kwargs):
        if getattr(msg, 'consistency_level', None) is None:
            # ResponseFuture._set_result requires message.consistency_level
            # for ServerError messages. PrepareMessage for instance doesn't
            # have this attribute set, so it crashes with AttributeError
            msg.consistency_level = None
        routing_key = getattr(msg, 'routing_key', b'')
        proxied_msg = ProxiedMessage(msg, routing_key)
        return super().send_msg(proxied_msg, *args, **kwargs)


class ProxySession(Session):

    def _create_response_future(self, *args, **kwargs):
        future = super()._create_response_future(*args, **kwargs)
        default_routing_key = b''
        routing_key = future.query.routing_key or default_routing_key
        future.message.routing_key = routing_key
        return future
