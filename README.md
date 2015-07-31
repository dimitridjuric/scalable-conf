###Scalable Conf
##Udacity Fullstack Nanodegree Project 4

##Sessions

I've added a Session ndb class to models.py.
The fields are:
**name**, **speaker**, **session_type**, **location** are StringProperty type. we want these field to be indexed. **speaker** is repeated as there can be multiple speakers for a session.
**highlights** is of TexProperty type, we don't need this field to be indexed.
**start_time** is an IntegerProperty type. I tried to use a TimeProperty but ran into problems as ndb saves those a differently to standard python datetime.time(). This added complexity and made the application harder to maintain with a lot of code just used to convert times for the queries. I'm using an integer representation of 24h time HHMM (e.g 1245 is 12:45).
**date** is a DateProperty and **duration** is IntegerProperty in number of minutes.

The ProtoRPC message classes are **SessionForm** a copy of the session class in string format, and **SessionForms** a repeated SessionForm message.

I've decided not to implement the speaker as a separate class because the speaker entity would have to be created prior to creating the session, not something particularly user friendly.

 