from dataclasses import dataclass

from channels_simplify.consumers import SimpleConsumer, SimpleEvent, TargetsEnum, Message, Payload
from channels_simplify.decoratos import check_recipient_not_me


class TestConsumer(SimpleConsumer):
    authed = False
    broadcast_group = 'test_consumer'

    class TestEventAllAndSelf(SimpleEvent):
        request_payload_type = None
        target = TargetsEnum.for_all

        def initiator_catch(self, message: Message, payload: request_payload_type):
            """
            Client send test.event.all.and.self signal, and receive same signal

            Event name parsed from class name and formatted from Camel to Dot case
            """
            self.fire()

        def target_catch(self, message: Message, payload: request_payload_type):
            """
            Client send test.event.all.and.self signal, and anyone except self receive same signal

            Also, you can set payload if you need, is pretty simple
            """
            self.fire(payload={'Oh...': 'All except initiator receive that message'})

    class TestEventSelfOnly(SimpleEvent):
        request_payload_type = None
        target = TargetsEnum.for_initiator

        @dataclass
        class SadResponsePayload(Payload):
            so_sad: str = 'No one will be see this'
            additional_message: str = None

        def initiator_catch(self, message: Message, payload: request_payload_type):
            """
            Client send test.event.self.only signal, and receive same signal

            Also, you can make and return event if you need and set additional payload sure
            """
            return self.return_event(payload={'For who?': 'For me only sure'})

        def target_catch(self, message: Message, payload: request_payload_type):
            """
            This block will be ignored, if target type is for_initiator

            We can provide payload from special dataclass - Payload object
            So you can be sure that you sent everything correctly
            """
            return self.return_event(payload=self.SadResponsePayload(additional_message='A little new data'))

    class TestEventForSpecificUser(SimpleEvent):
        @dataclass
        class SpecificUserPayload(Payload):
            to_username: str

        request_payload_type = SpecificUserPayload
        target = TargetsEnum.for_user

        def initiator_catch(self, message: Message, payload: request_payload_type):
            """
            Client send test.event.for.specific.user signal, and receive same signal

            In request payload exist to_username key, for resolve who is specific user

            If request payload is wrong, initiator receive error and chain actions not be continued

            Also, you can access to payload sent from client
            """
            return self.return_event(payload={
                'Thanks for send signal': f'Cool, message to user - {payload.to_username} successfully sent'}
            )

        @check_recipient_not_me
        def target_catch(self, message: Message, payload: request_payload_type):
            """
            Client send test.event.for.specific.user signal, and specific user receive same signal

            You can fire or return another event if you need

            Specific user receive that
            {"event": "happy.receiver", "payload": {"Wow": "Specific user like it"}}
            """

            TestConsumer.HappyReceiver(consumer=self.consumer).fire(payload={'Wow': 'Specific user like it'})

    class HappyReceiver(SimpleEvent):
        """
        This event is hidden, you can't access for that from client side, it can be fired only from backend
        """
        hidden = True
        request_payload_type = None

        def target_catch(self, message: Message, payload: request_payload_type):
            """
            This block will be ignored if event call from backend side with .fire() or .return_event()

            From backend side you can imitate client side call with .fire_broadcast() and this block will be triggered
            Event will be force called Hidden will be ignored
            """
            self.fire(payload={'Very': 'Happy'})

        def initiator_catch(self, message: Message, payload: request_payload_type):
            """
            This block will be ignored if event call from backend side with .fire() or .return_event()

            From backend side you can imitate client side call with .fire_broadcast() and this block will be triggered
            Event will be force called Hidden will be ignored
            """
            self.fire(payload={'Very': 'Happy'})
