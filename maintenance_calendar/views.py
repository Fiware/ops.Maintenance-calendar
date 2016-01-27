import requests
from functools import wraps
from flask import json, session
import maintenance_calendar.common.util as util
from maintenance_calendar.calendar_synchronizer import CalendarSynchronizer
from maintenance_calendar import app
from flask import request
import re
from werkzeug.wrappers import Response

from maintenance_calendar.validator import factory_selector
from maintenance_calendar.model import Calendar, Event
from exceptions import UnAuthorizedMethodError

from maintenance_calendar import config

# set the secret key.  keep this really secret:
#To generate the new secret Key use this:
#>>> import os
#>>> os.urandom(24)
app.secret_key = '\x14B\t\xeeEY\xa0\x96O\xac\xd0\xa7;;f\x06\xd7&y\xd6\xd9\xab`{'

#authentication and authorization part
def check_auth(token):
    """This function is called to check if the token is valid
    """
    chech_auth = False
    url_keystone = config.url_keystone + token
    responseToken = requests.get(url_keystone)
    if (responseToken.status_code == 200):
        try:
            user = json.loads(responseToken.content)
            session['user'] = user
            chech_auth = True
        except Exception, e:
            print "check_auth(): Error - " + str(e)
            chech_auth = False
    else:
        chech_auth = False
    return chech_auth

def authenticate():
    """Sends a 401 response that enables Auth2 authentication"""
    return Response(
    'Could not verify your access level for that URL.\n'
    'You have to login with proper token', 401,
    {'X-Auth-Token': 'Auth2 realm="Token Required"'})

def authorization():
    """Sends a 401 response that enables Auth2 authentication"""
    print "authorization!!!!!!"
    return Response(
    'The method specified in the Request-Line is not allowed for the resource identified by the Request-URI.\n', 405 )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Auth-Token')
        if not token or not check_auth(token):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


def authorization(location):
    ##This method is reponsible to manage the authorization for the different events.
    ##This method validate if the user has the apropiate rol for manage events for one node or for non-maintenance periods
    is_authorized = False
    try:
        user = session['user']
        if location == 'UptimeRequests':
            #validate if the user has privileges to manage the events of the non-maintenance periods
            roles = user['roles']
            for role in roles:
                role_name =  role['name']
                if role_name=='UptimeRequester':
                    is_authorized = True
                    break

        else:
            #validate if the user has privileges to manage the events of this node
            organizations = user['organizations']
            print organizations
            
            for organization in organizations:
                name = organization['name']
                position = name.find("FIDASH")
                if position != -1:
                    name_organization = name[:position-1]
                    if name_organization==location:
                        roles = organization['roles']
                        for role in roles:
                            role_name =  role['name']
                            if role_name=='InfrastructureOwner':
                                is_authorized = True
                                break
                        break

    except Exception, e:
            #any error indicate that the structure is not correct and we don't allow to connect for this user.
            is_authorized = False
            print 'Error authorization for location !!!' + location 
            print e
    if not is_authorized:
        raise UnAuthorizedMethodError()
        

#definition of the different views
@app.errorhandler(404)
def not_found(error):
    return "The requested resource does not exist", 404

@app.errorhandler(UnAuthorizedMethodError)
def not_authorized(error):
    return "The method specified in the Request-Line is not allowed for the resource identified by the Request-URI.", 405

@app.route('/api/v1')
@requires_auth
def hello_world():
    return 'Hello World! '
  

@app.route("/api/v1/events", methods=['GET'])
@requires_auth
def get_events():

    location = request.args.get('location')
    start_date = request.args.get('start')
    end_date = request.args.get('end')
    
    
    print "args", location, start_date, end_date
    calendarSynchronizer = CalendarSynchronizer()
    calendar_collection = calendarSynchronizer.get_events(location, start_date, end_date)
    response_body = calendar_collection.serialize(request.accept_mimetypes)  
    return Response(response_body, mimetype=request.accept_mimetypes[0][0]) 

@app.route("/api/v1/events", methods=['POST'])
@requires_auth
def create_event():
    body = util.remove_non_usable_characters(
                        util.remove_xml_header(request.data.decode("utf-8")))
    content_type = request.content_type
    validator_factory = factory_selector.get_factory(content_type)
    validator = validator_factory.create_event_request_validator()
    validator.validate(body)

    event = Event.deserialize(content_type, body)

    #validate the authorization to create it 
    print event.location
    authorization(event.location)

    manager = CalendarSynchronizer()
    new_event = manager.register_event(event)
    
    response_body = new_event.serialize(request.accept_mimetypes)
    
    return Response(response_body, status=201, mimetype=request.accept_mimetypes[0][0])

@app.route("/api/v1/events/<event_id>", methods=['GET'])
@requires_auth
def get_event(event_id):

    manager = CalendarSynchronizer()
    event = manager.get_event(event_id)
    response_body = event.serialize(request.accept_mimetypes)
    return Response(response_body, status=200, mimetype=request.accept_mimetypes[0][0])


#To be confirmed if the radicalle accept modify a calendar event
@app.route("/api/v1/events/<event_id>", methods=['PUT'])
@requires_auth
def modify_event(event_id):
    return 'Not implemented, modifying event {0}'.format(event_id)

@app.route("/api/v1/events/<event_id>", methods=['DELETE'])
@requires_auth
def delete_event(event_id):

    manager = CalendarSynchronizer()
    #before to remoe it, we need to collect the event to know the location, we don't want to delegate this action to the CalendarSynchronizer
    #if we didn't want to create two calls to the calendar, we will need to translate this validation to the CalendarSynchronizer
    event = manager.get_event(event_id)
    #validate the authorization to delete it
    authorization(event.location)

    status = manager.remove_event(event_id)
    if status:
        return Response(status=204)
    else:
        return Response('Not Found Event', status=404)

if __name__ == '__main__':
    app.run()

