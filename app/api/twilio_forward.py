# from fastapi import APIRouter
# from fastapi.responses import Response

# router = APIRouter()

# @router.post("/twilio/forward")
# async def forward_call():
#     twiml = """
#     <Response>
#         <Dial>
#             +919834292962
#         </Dial>
#     </Response>
#     """
#     return Response(content=twiml, media_type="application/xml")
