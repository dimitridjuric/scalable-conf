# Scalable Conf
#### Udacity Fullstack Nanodegree Project 4
---


### Sessions

I've added a Session ndb class to models.py.
The fields are:
**name**, **speaker**, **session_type**, **location** are StringProperty type. we want these fields to be indexed. **speaker** is repeated as there can be multiple speakers for a session.
**highlights** is of TexProperty type, we don't need this field to be indexed.
**start_time** is an IntegerProperty type. I've tried to use a TimeProperty but ran into problems as ndb saves those differently to a standard python datetime.time(). This added complexity and made the application harder to maintain with a lot of code just used to convert times for the queries. I'm using an integer representation of 24h time HHMM (e.g 1245 is 12:45).
**date** is a DateProperty and **duration** is IntegerProperty in number of minutes.

The ProtoRPC message classes are **SessionForm** a copy of the session class in string format, and **SessionForms** a repeated SessionForm message.

I've decided not to implement the speaker as a separate class because the speaker entity would have to be created prior to creating the session, not something I find particularly user friendly. Speaker is a repeated string property of the Session class 

#### Endpoints

**createSession** has the same structure as **createConference**. I use a **_createSessionObject** function to get the user profile and the conference object. The conference is the parent of the session which makes querying for all sessions of a conference easy with an ancestor query. I check if the session date is within the dates of the conference. I put the **getFeaturedSpeaker** code in **createConference** as well, this will be discussed later.

**getConferenceSessions** is a straightforward ancestor query with ordering by date and time. It takes a websafe conference key in the url path.

**getConferenceByType** is a query with a filter on **session_type**

**getSessionBySpeaker** is also a query with filter across all sessions of all conferences. 



### Wishlists

I've implemented wishlist as another property of the **Profile** class. It's similar to the **conferenceKeysToAttend** property, a repeated StringProperty
where we add the session keys.

#### Endpoints

**addSessionToWishlist** takes a session key in the url path. It calls **_wishlistAddition**. This function gets the profile of the registed user, checks if the session is in the wishlist and appends the websafe session key to the list. _wishlistAddition also take an optional argument, **addition**, if set to False it removes the sessionKey from the wishlist. this is used by the **removeSessionFromWishlist** endpoint.

**getSessionInWishlist** returns the list of sessions in the user's wishlist.


### Additional Queries


**querySessions** is a general query endpoint that allows to query on any field. It can be used with a websafe Conference Key, in which case it limits the query to the session of that conference. If the websafeConferenceKey field is left empty, then the query will be on all sessions across conferences the user is registered for. This endpoint only allows for one filter at a time.

**doubleQuerySession** is also a general query endpoint. It allows queries on two fields of the session class with any operator. It allows two inequalities on different fields.


#### Query related problem

the **doubleQuerySession** endpoint is a solution to the query problem. For this we can't use **ndb** for queries with inequalities on two different properties. So the function runs the first query and if the operators of both queries are inequalities, the second query is done in memory by the function, looping through the results of the first query. We can easily imagine situations where this wouldn't be practical, when the size of the result of the first query would be too large. But for our example, conferences, even large ones only have so many sessions so it shouldn't be a problem.


#### Index

Since **doubleQuerySession** queries on multiple properties we need to make sure the multi-property indices are built and listed in index.yaml. I've run queries on each pair of properties on the local developement server. This is a bit tedious but is a good way to test the app.


## Featured Speaker

For this functionality, I've added some code to **createSession**. When a new session is created, each speaker for this session is checked. If the speaker is already in another session he becomes the featured speaker. We store the featured speaker and session name in memcache.

To get all the speakers for a conference we use **_getSpeakers**. This function gets all the speakers for a conference. I've also added another endpoint using this function **getConferenceSpeakers**.

**getFeaturedSpeaker** just gets the featured speaker and session name from the memcache, and returns a StringMessage.

