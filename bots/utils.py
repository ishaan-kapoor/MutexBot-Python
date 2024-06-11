import re

from botbuilder.schema import ChannelAccount, Mention, Activity, ConversationParameters
from botbuilder.schema._models_py3 import ErrorResponseException
from botbuilder.core import MessageFactory, TurnContext
from pymongo import MongoClient
from datetime import datetime, timezone, timedelta
from typing import List
from botbuilder.core.teams import TeamsInfo
from botbuilder.schema.teams import TeamsChannelAccount

now = lambda: datetime.now(tz=timezone.utc).replace(tzinfo=None)
future = lambda: now() + timedelta(weeks=10000)
past = lambda: now() - timedelta(weeks=10000)


class MongoActions:
    mongo_connection = MongoClient("localhost", 27017)
    mongo_db = mongo_connection["sprinklr"]
    users = mongo_db["users"]
    jenkins_resources = mongo_db["jenkins-resources"]
    default_user_record = {}
    default_resource_record = {
        "reserved": False,
        "reserved-by": "666039258ad8bf7b8cc6bd5c",
        "monitored-by": [],
        "reserved-till": past(),
    }

    @staticmethod
    def get_resource(name: str) -> dict:
        resource = MongoActions.jenkins_resources.find_one({"name": name})
        if resource is None:
            MongoActions.make_resource(name)
            resource: dict = MongoActions.get_resource(name)
        resource["reserved"] &= resource["reserved-till"] >= now()
        return resource

    @staticmethod
    def make_resource(name: str) -> str:
        resource_id = MongoActions.jenkins_resources.insert_one(
            {"name": name, **MongoActions.default_resource_record}
        )
        if resource_id is None:
            raise Exception("Resource could not be created")
        return resource_id

    @staticmethod
    def get_user(id: str, name: str = "") -> dict:
        # name is not a required parameter, include it to give the correct name to the user document
        user = MongoActions.users.find_one({"id": id})
        if user is None:
            MongoActions.make_user(id, name)
            user: dict = MongoActions.get_user(id, name)
        return user

    @staticmethod
    def make_user(id: str, name: str) -> str:
        user_id = MongoActions.users.insert_one(
            {"id": id, "name": name, **MongoActions.default_user_record}
        )
        if user_id is None:
            raise Exception("User could not be created")
        return user_id


class Actions:

    @staticmethod
    async def send_personal_message(turn_context: TurnContext, app_id: str, recipient: TeamsChannelAccount, message: Activity | str
    ) -> None:
        conversation_reference = TurnContext.get_conversation_reference(turn_context.activity)

        conversation_parameters = ConversationParameters(
            is_group=False,
            bot=turn_context.activity.recipient,
            members=[recipient],
            tenant_id=turn_context.activity.conversation.tenant_id,
        )

        async def get_ref(tc1):
            conversation_reference_inner = TurnContext.get_conversation_reference(
                tc1.activity
            )
            return await tc1.adapter.continue_conversation(
                conversation_reference_inner, send_message, app_id
            )

        async def send_message(tc2: TurnContext):
            return await tc2.send_activity(message)

        try:
            await turn_context.adapter.create_conversation(
                conversation_reference, get_ref, conversation_parameters
            )
        except ErrorResponseException as err:
            if (
                "(BadArgument) Bot is not installed in user's personal scope"
                in err.message
            ):
                print(f"Bot is not installed in {recipient.name}'s personal scope.")
                # await turn_context.send_activity(f"Bot is not installed in {recipient['name']}'s personal scope.")

    @staticmethod
    async def get_members(turn_context: TurnContext) -> List[TeamsChannelAccount]:
        paged_members: List[TeamsChannelAccount] = []
        continuation_token = None
        while True:
            current_page = await TeamsInfo.get_paged_members(
                turn_context, continuation_token, 100
            )
            continuation_token = current_page.continuation_token
            paged_members.extend(current_page.members)
            if continuation_token is None:
                break
        return paged_members

    @staticmethod
    async def find_member(
        turn_context: TurnContext, id: str
    ) -> TeamsChannelAccount | None:
        continuation_token = None
        while True:
            current_page = await TeamsInfo.get_paged_members(
                turn_context, continuation_token, 100
            )
            continuation_token = current_page.continuation_token
            for member in current_page.members:
                if member.id == id:
                    return member
            if continuation_token is None:
                break
        return None

    @staticmethod
    async def reserve_resource(
        user_record: ChannelAccount,
        resource: str,
        turn_context: TurnContext,
        app_id: str,
        duration: int,
    ) -> Activity | str:
        resource_record: dict = MongoActions.get_resource(resource)
        # unused but it creates a user, if not there
        user_record: dict = MongoActions.get_user(user_record.id, user_record.name)

        if resource_record["reserved"] is True:
            reserving_user_record = MongoActions.get_user(
                resource_record["reserved-by"]
            )
            reserving_user = await Actions.find_member(
                turn_context, resource_record["reserved-by"]
            )
            if reserving_user is not None:
                mention = Mention(
                    mentioned=reserving_user,
                    text=f"<at>{reserving_user.name}</at>",
                    type="mention",
                )
                name = mention.text
            else:
                name = reserving_user_record["name"]
            message: str = (
                f'Resource "{resource}" is already reserved by {name}, till {time2hyperlink(resource_record["reserved-till"])}.'
            )
            response: Activity = MessageFactory.text(message)
            if reserving_user is not None:
                response.entities = [Mention().deserialize(mention.serialize())]
            return response

        # user_record["resources"].append(resource_record["_id"])
        # MongoActions.users.replace_one({"_id": user_record["_id"]}, user_record)
        resource_record["reserved"] = True
        resource_record["reserved-by"] = user_record.id
        resource_record["reserved-till"] = now() + timedelta(minutes=duration)
        resource_record["monitored-by"] = [
            i for i in resource_record["monitored-by"] if i["till"] >= now()
        ]
        MongoActions.jenkins_resources.replace_one(
            {"_id": resource_record["_id"]}, resource_record
        )

        mention = Mention(mentioned=user_record, text=f"<at>{user_record.name}</at>", type="mention")
        message: str = (
            f'{mention.text if mention is not None else user_record.name} reserved "{resource}" till {time2hyperlink(resource_record["reserved-till"])}.'
        )
        response: Activity = MessageFactory.text(message)
        if mention is not None:
            response.entities = [Mention().deserialize(mention.serialize())]

        for record in resource_record["monitored-by"]:
            user_record: dict = MongoActions.get_user(record["id"])
            if user_record is None:
                continue
            user = TeamsChannelAccount(user["id"], user["name"])
            await Actions.send_personal_message(turn_context, app_id, user, response)

        return response

    @staticmethod
    async def release_resource(
        user: ChannelAccount, resource: str, turn_context: TurnContext, app_id: str
    ) -> Activity:
        resource_record: dict = MongoActions.get_resource(resource)

        if resource_record["reserved"] is False:
            return f'Resource "{resource}" is not reserved by anyone.'

        if user.id != resource_record["reserved-by"]:
            reserving_user_record = MongoActions.get_user(
                resource_record["reserved-by"]
            )
            reserving_user = await Actions.find_member(
                turn_context, resource_record["reserved-by"]
            )
            if reserving_user is not None:
                mention = Mention(
                    mentioned=reserving_user,
                    text=f"<at>{reserving_user.name}</at>",
                    type="mention",
                )
                name = mention.text
            else:
                name = reserving_user_record["name"]
            message: str = (
                f'Resource "{resource}" is reserved by {name}, till {time2hyperlink(resource_record["reserved-till"])}.\nOnly they can release it.'
            )
            response: Activity = MessageFactory.text(message)
            if reserving_user is not None:
                response.entities = [Mention().deserialize(mention.serialize())]
            return response

        resource_record["reserved"] = False
        resource_record["monitored-by"] = [
            i for i in resource_record["monitored-by"] if i["till"] >= now()
        ]
        MongoActions.jenkins_resources.replace_one(
            {"_id": resource_record["_id"]}, resource_record
        )

        mention = Mention(mentioned=user, text=f"<at>{user.name}</at>", type="mention")
        message: str = f'{mention.text} released "{resource}"'
        response: Activity = MessageFactory.text(message)
        response.entities = [Mention().deserialize(mention.serialize())]

        for user_id in resource_record["monitored-by"]:
            user = MongoActions.get_user(user_id["id"])
            if user is not None:
                await Actions.send_personal_message(
                    turn_context, app_id, user, response
                )

        return response

    @staticmethod
    async def monitor_resource(
        user: ChannelAccount, resource: str, duration: int
    ) -> Activity:
        resource_record: dict = MongoActions.get_resource(resource)

        resource_record["monitored-by"] = [
            i for i in resource_record["monitored-by"] if i["till"] >= now()
        ]
        for i in resource_record["monitored-by"]:
            if i["id"] == user.id:
                i["till"] = max(i["till"], now() + timedelta(minutes=duration))
                break
        else:
            resource_record["monitored-by"].append(
                {"id": user.id, "till": now() + timedelta(minutes=duration)}
            )
        MongoActions.jenkins_resources.replace_one(
            {"_id": resource_record["_id"]}, resource_record
        )

        mention = Mention(mentioned=user, text=f"<at>{user.name}</at>", type="mention")
        message: str = (
            f'{mention.text} is monitoring "{resource}" for {duration} minutes'
        )
        response: Activity = MessageFactory.text(message)
        response.entities = [Mention().deserialize(mention.serialize())]
        return response

    @staticmethod
    async def stop_monitoring_resource(user: ChannelAccount, resource: str) -> Activity:
        resource_record: dict = MongoActions.get_resource(resource)

        resource_record["monitored-by"] = [
            i
            for i in resource_record["monitored-by"]
            if ((i["id"] != user.id) and (i["till"] >= now()))
        ]
        MongoActions.jenkins_resources.replace_one(
            {"_id": resource_record["_id"]}, resource_record
        )

        mention = Mention(mentioned=user, text=f"<at>{user.name}</at>", type="mention")
        message: str = f'{mention.text} stopped monitoring "{resource}"'
        response: Activity = MessageFactory.text(message)
        response.entities = [Mention().deserialize(mention.serialize())]
        return response

    @staticmethod
    async def status_of_resource(
        user: ChannelAccount, resource: str, turn_context: TurnContext
    ) -> Activity:
        resource_record: dict = MongoActions.get_resource(resource)

        if resource_record["reserved"] is False:
            return f'Resource "{resource}" is not reserved by anyone.'

        reserving_user_record = MongoActions.get_user(resource_record["reserved-by"])
        reserving_user = await Actions.find_member(
            turn_context, resource_record["reserved-by"]
        )
        if reserving_user is not None:
            mention = Mention(
                mentioned=reserving_user,
                text=f"<at>{reserving_user.name}</at>",
                type="mention",
            )
            name = mention.text
        else:
            name = reserving_user_record["name"]
        message: str = (
            f'Resource "{resource}" is reserved by {name}, till {time2hyperlink(resource_record["reserved-till"])}.'
        )
        response: Activity = MessageFactory.text(message)
        if reserving_user is not None:
            response.entities = [Mention().deserialize(mention.serialize())]
        return response


def str2time(time_str: str) -> int:
    pattern = re.compile(r"(\d+)([hm])")
    matches = pattern.findall(time_str)

    total_minutes = 0
    for value, unit in matches:
        if unit == "h":
            total_minutes += int(value) * 60
        elif unit == "m":
            total_minutes += int(value)
    return total_minutes


def timeOverlap(
    from1: datetime, till1: datetime, from2: datetime, till2: datetime
) -> bool:
    if till1 < from1 or till2 < from2:
        return False
    if till1 < from2 or till2 < from1:
        return False
    return True


def time2str(time: datetime):
    return time.strftime("%H:%M:%S (%d/%m/%y)")


def time2link(time: datetime):
    return f"https://www.timeanddate.com/worldclock/fixedtime.html?day={time.day}&month={time.month}&year={time.year}&hour={time.hour}&min={time.minute}&sec={time.second}"


def time2hyperlink(time: datetime):
    return f"[{time2str(time)} UTC]({time2link(time)})"
