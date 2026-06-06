"""Strawberry GraphQL schema assembly."""
from __future__ import annotations

import strawberry
from strawberry.fastapi import GraphQLRouter

from vela.graphql.mutations import Mutation
from vela.graphql.resolvers import Query
from vela.graphql.subscriptions import Subscription

schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
)

graphql_router = GraphQLRouter(schema, graphiql=True)
