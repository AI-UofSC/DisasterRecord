#!/bin/bash

curl -X PUT "localhost:9200/"$1"-tweetneeds" -H 'Content-Type: application/json' -d'
{
  "mappings": {
    "doc": {
      "dynamic_templates": [
        {
          "strings": {
            "match_mapping_type": "string",
            "mapping": {
              "type": "keyword"
            }
          }
        }
      ],
      "properties": {
        "geometry": {
          "properties": {
            "type": {
              "type": "text"
            },
            "coordinates": {
              "type": "geo_point"
            }
          }
        },
        "type": {

              "type": "text"

        },
        "properties": {
          "properties": {
            "text": {
              "type": "text"
            },
            "image": {
              "properties": {
                "imageURL": {
                  "type": "keyword"
                },
                "objects": {
                  "properties": {
                    "person": {
                      "type": "integer"
                    },
                    "animal": {
                      "type": "integer"
                    },
                    "vehicles": {
                      "type": "integer"
                    }
                  }
                },
                "water": {
                  "type": "boolean"
                }
              }
            },
            "needClass": {
              "type": "keyword"
            },
            "tweetID": {
              "type": "long"
            },
            "flooded": {
              "type": "boolean"
            },
            "locationMention": {
              "properties": {
                "text": {
                  "type": "text","fielddata": true
                },
                "offsets": {
                  "type": "integer"
                }
              }
            },
            "createdAt": {
              "type": "date",
              "format": "yyyy-MM-dd HH:mm:ss||yyyy-MM-dd||epoch_millis"
            }
          }
        }
      }
    }
  }
}

'

