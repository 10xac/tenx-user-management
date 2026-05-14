class CommunicationManager:
    """All strapi queries are called from here"""
    def __init__(self):
        pass

    def _has_graphql_errors(self, result):
        return isinstance(result, dict) and bool(result.get("errors"))

    def _extract_trainee_batch_access_id(self, result):
        data = result.get("data", {}) if isinstance(result, dict) else {}
        access_data = data.get("traineeBatchAccesses", {}).get("data", [])
        if access_data:
            return access_data[0].get("id")

        for key in ("createTraineeBatchAccess", "updateTraineeBatchAccess"):
            access_id = data.get(key, {}).get("data", {}).get("id")
            if access_id:
                return access_id

        return None

    def _extract_reviewer_batch_access_id(self, result):
        data = result.get("data", {}) if isinstance(result, dict) else {}
        access_data = data.get("reviewerBatchAccesses", {}).get("data", [])
        if access_data:
            return access_data[0].get("id")

        return (
            data.get("createReviewerBatchAccess", {}).get("data", {}).get("id")
            or data.get("updateReviewerBatchAccess", {}).get("data", {}).get("id")
        )

    def _access_error_response(self, error_type, message, parent_key, parent_id, batch_id, access_result, cleanup_result=None):
        return {
            "error": True,
            "error_type": error_type,
            "message": message,
            parent_key: parent_id,
            "batch_id": batch_id,
            "access_result": access_result,
            "cleanup_result": cleanup_result
        }
    
    def create_user(self, sg, user_data):
        """
        Create a new user using the provided user data and return the result in JSON format.

        Parameters:
            sg: graphql object for interacting with the database
            user_data: a dictionary containing user's username and email

        Returns:
            result_json: the result of the user creation in JSON format
        """
        
        query = """mutation createUser($username:String!,$email:String!, $password:String!) 
                    { register(input: { username: $username, email: $email, password: $password } ) 
                    { user { id username email }  } }"""
        username = user_data['name']+"_"+ user_data['email']

        variables = {"username": username, "email":user_data['email'], "password":user_data['password']}
        print("user data variables.....",variables)
        result_json = sg.Select_from_table(query=query, variables= variables)
        print("user data result json.....",result_json)
        return result_json
    
    def insert_all_users(self,sg, all_user_data):  
        query = """mutation createAllUser(
                $email: String
                $userId: ID
                $name: String
                $role: ENUM_ALLUSER_ROLE
                $batchId: [ID]
                $groups: [ID]
                ) {
                createAllUser(
                    data: {
                    email: $email
                    user: $userId
                    name: $name
                    role: $role
                    BatchIDs: $batchId
                    groups: $groups
                    }
                ) {
                    data {
                    id
                    }
                }
                }

                    """
        variables =  {"email": all_user_data['email'],"name":all_user_data['name'],
               
                        "userId": all_user_data['userId'], 
                        "role":all_user_data['role'],
                        "batchId": all_user_data['batchId'],
                        "groups": all_user_data['groups']
                        }

        result_json = sg.Select_from_table(query=query, variables= variables)
        print("all user data result json.....",result_json)
        return result_json

    def read_trainee_by_email(self, sg, email):
        query = """
            query getTraineeByEmail($email: String) {
                trainees(
                    pagination: { start: 0, limit: 1 }
                    filters: { email: { eq: $email } }
                ) {
                    data {
                        id
                        attributes {
                            email
                            trainee_id
                            all_user {
                                data {
                                    id
                                }
                            }
                        }
                    }
                }
            }
        """
        return sg.Select_from_table(query=query, variables={"email": email})

    def read_trainee_batch_access(self, sg, trainee_id, batch_id):
        query = """
            query getTraineeBatchAccess($traineeID: ID, $batchID: ID) {
                traineeBatchAccesses(
                    pagination: { start: 0, limit: 1 }
                    filters: {
                        trainee: { id: { eq: $traineeID } }
                        batch: { id: { eq: $batchID } }
                    }
                ) {
                    data {
                        id
                        attributes {
                            status
                            hasTenx
                            hasLeap
                        }
                    }
                }
            }
        """
        return sg.Select_from_table(
            query=query,
            variables={"traineeID": trainee_id, "batchID": batch_id}
        )

    def create_trainee_batch_access(self, sg, trainee_id, batch_id, status="Accepted", has_tenx=True, has_leap=False):
        query = """
            mutation createTraineeBatchAccess(
                $traineeID: ID
                $batchID: ID
                $status: Enum_Traineebatchaccess_Status
                $hasTenx: Boolean
                $hasLeap: Boolean
            ) {
                createTraineeBatchAccess(
                    data: {
                        trainee: $traineeID
                        batch: $batchID
                        status: $status
                        hasTenx: $hasTenx
                        hasLeap: $hasLeap
                    }
                ) {
                    data {
                        id
                        attributes {
                            hasTenx
                            hasLeap
                        }
                    }
                }
            }
        """
        variables = {
            "traineeID": trainee_id,
            "batchID": batch_id,
            "status": status,
            "hasTenx": has_tenx,
            "hasLeap": has_leap
        }
        return sg.Select_from_table(query=query, variables=variables)

    def update_trainee_batch_access(self, sg, access_id, status="Accepted", has_tenx=True):
        query = """
            mutation updateTraineeBatchAccess(
                $id: ID!
                $status: Enum_Traineebatchaccess_Status
                $hasTenx: Boolean
            ) {
                updateTraineeBatchAccess(
                    id: $id
                    data: {
                        status: $status
                        hasTenx: $hasTenx
                    }
                ) {
                    data {
                        id
                    }
                }
            }
        """
        variables = {
            "id": access_id,
            "status": status,
            "hasTenx": has_tenx
        }
        return sg.Select_from_table(query=query, variables=variables)

    def ensure_trainee_batch_access(self, sg, trainee_id, batch_id, status="Accepted", has_tenx=True, has_leap=False):
        existing = self.read_trainee_batch_access(sg, trainee_id, batch_id)
        if self._has_graphql_errors(existing):
            return existing

        access_data = existing.get("data", {}).get("traineeBatchAccesses", {}).get("data", [])
        if access_data:
            access_id = access_data[0]["id"]
            return self.update_trainee_batch_access(
                sg,
                access_id,
                status=status,
                has_tenx=has_tenx
            )

        return self.create_trainee_batch_access(
            sg,
            trainee_id,
            batch_id,
            status=status,
            has_tenx=has_tenx,
            has_leap=has_leap
        )

    def read_all_user_batch_groups(self, sg, all_user_id):
        query = """
            query getAllUserBatchGroups($id: ID!) {
                allUser(id: $id) {
                    data {
                        id
                        attributes {
                            BatchIDs {
                                data {
                                    id
                                }
                            }
                            groups {
                                data {
                                    id
                                }
                            }
                        }
                    }
                }
            }
        """
        return sg.Select_from_table(query=query, variables={"id": all_user_id})

    def update_all_user_batch_groups(self, sg, all_user_id, batch_ids, group_ids):
        query = """
            mutation updateAllUserBatchGroups($id: ID!, $batchIDs: [ID], $groupIDs: [ID]) {
                updateAllUser(
                    id: $id
                    data: {
                        BatchIDs: $batchIDs
                        groups: $groupIDs
                    }
                ) {
                    data {
                        id
                    }
                }
            }
        """
        variables = {
            "id": all_user_id,
            "batchIDs": batch_ids,
            "groupIDs": group_ids
        }
        return sg.Select_from_table(query=query, variables=variables)

    def ensure_all_user_batch_group(self, sg, all_user_id, batch_id=None, group_id=None):
        if not all_user_id:
            return {
                "error": True,
                "error_type": "ALL_USER_BATCH_GROUP_ERROR",
                "message": "AllUser batch/group update requires an all_user id",
                "alluser_id": all_user_id,
                "batch_id": batch_id,
                "group_id": group_id
            }

        existing = self.read_all_user_batch_groups(sg, all_user_id)
        if self._has_graphql_errors(existing):
            return {
                "error": True,
                "error_type": "ALL_USER_BATCH_GROUP_ERROR",
                "message": "Failed to read existing AllUser batch/group relations",
                "alluser_id": all_user_id,
                "batch_id": batch_id,
                "group_id": group_id,
                "lookup_result": existing
            }

        all_user = existing.get("data", {}).get("allUser", {}).get("data", {})
        if not all_user:
            return {
                "error": True,
                "error_type": "ALL_USER_BATCH_GROUP_ERROR",
                "message": "AllUser was not found; refusing to overwrite batch/group relations",
                "alluser_id": all_user_id,
                "batch_id": batch_id,
                "group_id": group_id,
                "lookup_result": existing
            }

        attributes = all_user.get("attributes", {}) if all_user else {}

        batch_ids = [
            item["id"]
            for item in attributes.get("BatchIDs", {}).get("data", [])
            if item.get("id")
        ]
        group_ids = [
            item["id"]
            for item in attributes.get("groups", {}).get("data", [])
            if item.get("id")
        ]

        if batch_id and str(batch_id) not in batch_ids:
            batch_ids.append(str(batch_id))
        if group_id and str(group_id) not in group_ids:
            group_ids.append(str(group_id))

        return self.update_all_user_batch_groups(sg, all_user_id, batch_ids, group_ids)

    def read_all_users(self,sg, req_params):
        query = """ query getAllUser($batch:Int,$role:String){
                allUsers(pagination:{start:0, limit:2000} filters:{Batch:{eq:$batch}, role:{eq:$role}}){
                    meta{
                    pagination{
                        total
                    }
                    }
                    data{
                    id
                    attributes{
                        name
                        email
                        Batch
                      	user{
                          data{
                            id
                            attributes{
                              email
                            }
                          }
                        }
                    }
                    }
                }
                }
            """
        result_json = sg.Select_from_table(query=query, variables={"batch":req_params['batch'], "role": req_params['role']})
        return result_json
    
    def create_new_batch (self, sg,  batchparams ):
        """
        A function to create a new batch using the provided batch parameters and return the result JSON.
        
        Parameters:
            sg (object): An object used to interact with the database.
            batchparams (dict): A dictionary containing batch parameters such as batch number, class link, communication link, and additional information.
        
        Returns:
            dict: A JSON object containing the result of creating the new batch.
        """
        query = """mutation createBatch(
                $batch: Int
                $class_link: String
                $communication_link: String
                $additional_info: JSON
                ) {
                createBatch(data: {
                    Batch:$batch
                    Class_link:$class_link
                    Communication_link:$communication_link
                    additional_info:$additional_info
                    
                }) {
                    data {
                    id
                    }
                }
                }"""
        

        result_json = sg.Select_from_table(query=query, variables={"batch":batchparams['batch'], "class_link":batchparams['class_link'], 
                                                                   "communication_link":batchparams['communication_link'], 
                                                                   "additional_info":batchparams['additional_info']}) 
        return result_json
    

    def read_batch_information(self, sg, batch_params):
        bquery = """
            query getBatch($batch:Int){
            batches(filters: { Batch:  { eq: $batch } }){
                data{
                id
                attributes{
                    Batch
                    
                }
                }
            }
            }

            """
        # batch = int(self.batch.split("-")[1])
        batchJson = sg.Select_from_table(query=bquery, variables={"batch": batch_params['batch']})
        return batchJson
    
    def read_batch_from_batch_ID(self, sg, batch_id):
        query = """query getBatch($batch_ID:ID){
            batches(filters: { id:  { eq: $batch_ID } }){
                data{
                id
                attributes{
                    Batch
                    
                }
                }
            }
            }"""
        batchJson = sg.Select_from_table(query=query, variables={"batch_ID": batch_id})
     
        return batchJson
    def create_reviewer(self, sg, reviewer_data):
        query = """mutation createReviewer($allUserID:ID,$email:String){
            createReviewer(data:{all_user:$allUserID,Email:$email}){
                data{
                id
                attributes{
                    Email
                }
                }
            }
            }"""
        result_json = sg.Select_from_table(query=query,variables =  {"allUserID": reviewer_data['all_user'],
                                                                     "email": reviewer_data['Email']})
        if self._has_graphql_errors(result_json):
            return result_json

        reviewer_id = result_json.get("data", {}).get("createReviewer", {}).get("data", {}).get("id")
        if not reviewer_id:
            return self._access_error_response(
                "REVIEWER_CREATION_ERROR",
                "Reviewer creation did not return an id",
                "reviewer_id",
                reviewer_id,
                reviewer_data.get("batches"),
                result_json
            )

        batch_id = reviewer_data.get("batches")
        if not batch_id:
            cleanup_result = self.delete_reviewer(sg, reviewer_id)
            return self._access_error_response(
                "REVIEWER_BATCH_ACCESS_ERROR",
                "Reviewer batch access is required but no batch id was provided",
                "reviewer_id",
                reviewer_id,
                batch_id,
                {},
                cleanup_result
            )

        access_result = self.ensure_reviewer_batch_access(sg, reviewer_id, batch_id)
        result_json["reviewer_batch_access"] = access_result
        access_id = self._extract_reviewer_batch_access_id(access_result)
        if self._has_graphql_errors(access_result) or not access_id:
            cleanup_result = self.delete_reviewer(sg, reviewer_id)
            return self._access_error_response(
                "REVIEWER_BATCH_ACCESS_ERROR",
                "Reviewer batch access could not be created or confirmed; reviewer was cleaned up",
                "reviewer_id",
                reviewer_id,
                batch_id,
                access_result,
                cleanup_result
            )

        return result_json

    def read_reviewer_batch_access(self, sg, reviewer_id, batch_id):
        query = """
            query getReviewerBatchAccess($reviewerID: ID, $batchID: ID) {
                reviewerBatchAccesses(
                    pagination: { start: 0, limit: 1 }
                    filters: {
                        reviewer: { id: { eq: $reviewerID } }
                        batch: { id: { eq: $batchID } }
                    }
                ) {
                    data {
                        id
                    }
                }
            }
        """
        return sg.Select_from_table(
            query=query,
            variables={"reviewerID": reviewer_id, "batchID": batch_id}
        )

    def create_reviewer_batch_access(self, sg, reviewer_id, batch_id, has_tenx=True, has_leap=False):
        query = """
            mutation createReviewerBatchAccess(
                $reviewerID: ID
                $batchID: ID
                $hasTenx: Boolean
                $hasLeap: Boolean
            ) {
                createReviewerBatchAccess(
                    data: {
                        reviewer: $reviewerID
                        batch: $batchID
                        hasTenx: $hasTenx
                        hasLeap: $hasLeap
                    }
                ) {
                    data {
                        id
                    }
                }
            }
        """
        variables = {
            "reviewerID": reviewer_id,
            "batchID": batch_id,
            "hasTenx": has_tenx,
            "hasLeap": has_leap
        }
        return sg.Select_from_table(query=query, variables=variables)

    def update_reviewer_batch_access(self, sg, access_id, has_tenx=True):
        query = """
            mutation updateReviewerBatchAccess(
                $id: ID!
                $hasTenx: Boolean
            ) {
                updateReviewerBatchAccess(
                    id: $id
                    data: {
                        hasTenx: $hasTenx
                    }
                ) {
                    data {
                        id
                    }
                }
            }
        """
        variables = {
            "id": access_id,
            "hasTenx": has_tenx
        }
        return sg.Select_from_table(query=query, variables=variables)

    def ensure_reviewer_batch_access(self, sg, reviewer_id, batch_id, has_tenx=True, has_leap=False):
        existing = self.read_reviewer_batch_access(sg, reviewer_id, batch_id)
        if self._has_graphql_errors(existing):
            return existing

        access_data = existing.get("data", {}).get("reviewerBatchAccesses", {}).get("data", [])
        if access_data:
            return self.update_reviewer_batch_access(
                sg,
                access_data[0]["id"],
                has_tenx=has_tenx
            )

        return self.create_reviewer_batch_access(
            sg,
            reviewer_id,
            batch_id,
            has_tenx=has_tenx,
            has_leap=has_leap
        )
    def create_user_preference(self, sg, user_preference_data):
        query = """mutation createPreference(
                $mainUserID: ID
                $email: String
                $defaultSettings: JSON
                ) {
                createPreference(
                    data: {
                    defaultSettings: $defaultSettings
                    email: $email
                    users_permissions_user: $mainUserID
                    }
                ){
                    data{
                    id
                    }
                }
                }"""
        result_json = sg.Select_from_table(query=query, variables= {"mainUserID":user_preference_data['main_user_id'],
                                                                     "email": user_preference_data['email'],
                                                                     "defaultSettings":user_preference_data['defaultSettings']})
        return result_json
    def create_group_for_staff(self, sg, group_params):
        """Don't run as it is check for the default value """
        query = """mutation createGroupStaff($alluserIDS:[ID]){
            createGroup(data:{Name:"Staff",all_users:$alluserIDS}){
                data{
                id
                }
            }
            }"""
        groupJson = sg.Select_from_table(query=query, variables={"alluserIDS": group_params['alluserIDS']})
        return groupJson
    
    def read_batch_specific_reviewers(self, sg, batch):
        """
            Function to get current batch from strapi graphql

        Args:
            Self.batch (Int): Number that represent current batch 

        Returns:
            Strapi Id of the imputed batch 
        """
        bquery = """

            query getReviewer($batch: Int) {
                    reviewers(
                        pagination: { start: 0, limit: 100 }
                        filters: {
                            reviewer_batch_accesses: {
                                batch: { Batch: { eq: $batch } }
                                hasTenx: { eq: true }
                            }
                        }
                    ) {
                        data {
                        id
                        attributes {
                            Email
                        }
                        }
                    }
                    }
            """
        batchJson = sg.Select_from_table(query=bquery, variables={"batch": batch})
        return batchJson
    
   
    def insert_profile_information(self, sg, row):
        query = """mutation createProfileInformation(
            $firstName: String
            $surName: String
            $nationality: String
            $gender:String
            $email:String
  			$date_of_birth:Date
            $all_user:ID
  			$other_info:JSON
            $bio:String
            $city_of_residence:String
        ) {
            createProfileInformation(
            data: {
                first_name: $firstName
                surname: $surName
                nationality: $nationality
                gender:$gender
                all_user:$all_user
                email:$email
              	date_of_birth:$date_of_birth
              	other_info: $other_info
                bio:$bio
                city_of_residence:$city_of_residence
            }
            ) {
            data {
                id
            }
            }
        }"""
        print("profile row ......", row)    
     
      
        result_json = sg.Select_from_table(query=query, variables= { "firstName": row['first_name'],
                                                                        "surName": row['last_name'],
                                                                        "nationality": row["nationality"],
                                                                        "gender": row["gender"],
                                                                        "all_user": row["all_user"],
                                                                        "email": row["email"],
                                                                        "other_info": row["other_info"],
                                                                        "date_of_birth": row["date_of_birth"],
                                                                        "bio": row["bio"],
                                                                        "city_of_residence": row["city_of_residence"]
                                                                        })
        # print("result_json ......", result_json)
        return result_json
    
    def insert_trainee_information(self, sg,  row):
        query = """mutation createTrainees(
                    $email: String
                    $alluser: ID
                    $traineeID: String
                    $batch: ID
                    $status: Enum_Trainee_Status
                    ) {
                    createTrainee(
                        data: {
                        email: $email
                        Status: $status
                        all_user: $alluser
                        trainee_id: $traineeID
                        batch:$batch
                        }
                    ) {
                        data {
                        id
                        }
                    }
                    }"""
        variables = dict(row)
        if "status" not in variables:
            variables["status"] = variables.get("Status", "Accepted")
        result_json = sg.Select_from_table(query=query, variables=variables)
        if self._has_graphql_errors(result_json):
            return result_json

        trainee_id = result_json.get("data", {}).get("createTrainee", {}).get("data", {}).get("id")
        if not trainee_id:
            return self._access_error_response(
                "TRAINEE_CREATION_ERROR",
                "Trainee creation did not return an id",
                "trainee_id",
                trainee_id,
                variables.get("batch"),
                result_json
            )

        batch_id = variables.get("batch")
        if not batch_id:
            cleanup_result = self.delete_trainee(sg, trainee_id)
            return self._access_error_response(
                "TRAINEE_BATCH_ACCESS_ERROR",
                "Trainee batch access is required but no batch id was provided",
                "trainee_id",
                trainee_id,
                batch_id,
                {},
                cleanup_result
            )

        access_result = self.ensure_trainee_batch_access(
            sg,
            trainee_id,
            batch_id,
            status=variables.get("status", "Accepted")
        )
        result_json["trainee_batch_access"] = access_result
        access_id = self._extract_trainee_batch_access_id(access_result)
        if self._has_graphql_errors(access_result) or not access_id:
            cleanup_result = self.delete_trainee(sg, trainee_id)
            return self._access_error_response(
                "TRAINEE_BATCH_ACCESS_ERROR",
                "Trainee batch access could not be created or confirmed; trainee was cleaned up",
                "trainee_id",
                trainee_id,
                batch_id,
                access_result,
                cleanup_result
            )

        return result_json
    
    def read_accepted_trainee(self,sg, trainee_params):
        bquery = """
                query get_trainee ($batch:Int, $status:String){
                    trainees(
                        pagination: { start: 0, limit: 1000 }
                        filters: {
                            trainee_batch_accesses: {
                                batch: { Batch: { eq: $batch } }
                                status: { eq: $status }
                                hasTenx: { eq: true }
                            }
                        }
                    ) {
                        meta {
                        pagination {
                            total
                        }
                        }
                        data {
                        attributes {
                            email
                            all_user {
                            data {
                                id
                                attributes {
                                email
                                }
                            }
                            }
                        }
                        }
                    }
                    }
            """
        traineeJson = sg.Select_from_table(
                                            query=bquery, 
                                            variables={"batch": trainee_params['batch'], 
                                                           "status": trainee_params['status']})
        return traineeJson

    def update_review_category_with_revewers(self, sg, reviview_category_params):
        query = """mutation updateReviewCategoryReviewers($id:ID!,$reviewers:[ID]){
            updateReviewCategory(id:$id,data:{reviewers:$reviewers}){
            data{
                attributes{
                name
                }
            }
            }
        }"""

        res = sg.Select_from_table(query = query, variables={'id': reviview_category_params['review_category_id'], 
                                                             'reviewers':reviview_category_params['reviewers']})
        return res
    def get_user_with_out_alluser( self, sg, role):
        query = """query getAllTrainees($role:String){
            usersPermissionsUsers(filters:{
                all_users:{id:{eq:null}}
                role:{name:{eq:$role}}}
            pagination:{start:0,limit:2000}){
                meta{
                pagination{
                    total
                }
                }
                data{
                id
                attributes{
                    email
                    username
                    all_users{
                    data{
                        attributes{
                        name
                        }
                    }
                    }
                }
                }
            }
            }"""
        result_json = sg.Select_from_table(query=query,variables =  {"role":role})
        return result_json
    
    def update_batch_user_for_group(self, sg, groupid : int, all_users_for_group):
        update_query = """mutation updateGroup($groupID:ID!,$allusersID:[ID]){
        updateGroup(id:$groupID,data:{all_users:$allusersID}){
            data{
            id
            }
        }
        }"""
        resu_json = sg.Select_from_table(query=update_query, variables={"groupID":groupid,"allusersID":all_users_for_group})
        print(resu_json)
        return resu_json
    
    def get_allUser_by_groupId(self, sg, groupId):
        query = """query getallUserID($groupID:ID){
        allUsers(
            pagination:{start:0,limit:2000}
            filters:{groups:{id:{eq:$groupID}}}){
            meta{
            pagination{
                total
            }
            }
            data{
            id
            }
        }
        }"""
        resu_json = sg.Select_from_table(query=query, variables={"groupID":groupId})
        with_group = [str(i['id']) for i in resu_json['data']['allUsers']['data']]
        return with_group
    
    def get_all_user_without_group (self, sg):
        query = """query getallUserID{
        allUsers(
            pagination:{start:0,limit:2000}
            filters:{groups:{id:{eq:null}}}){
            meta{
            pagination{
                total
            }
            }
            data{
            id
            }
        }
        }"""
        result_json = sg.Select_from_table(query=query, variables=None)
        without_group = [str(i['id']) for i in result_json['data']['allUsers']['data']]
        return without_group
    
    def get_user_with_out_alluser( self, sg, role):
        query = """query getAllTrainees($role:String){
                    usersPermissionsUsers(filters:{
                        all_users:{id:{eq:null}}
                        role:{name:{eq:$role}}}
                    pagination:{start:0,limit:2000}){
                        meta{
                        pagination{
                            total
                        }
                        }
                        data{
                        id
                        attributes{
                            email
                            username
                            all_users{
                            data{
                                attributes{
                                name
                                }
                            }
                            }
                        }
                        }
                    }
                    }"""
        result_json = sg.Select_from_table(query=query,variables =  {"role":role})
        return result_json

    def delete_user(self, sg, user_id: str):
        """Delete a user by ID"""
        query = """
        mutation deleteUser($id: ID!) {
            deleteUsersPermissionsUser(id: $id) {
                data {
                    id
                }
            }
        }
        """
        variables = {"id": user_id}
        return sg.Select_from_table(query, variables)

    def delete_alluser(self, sg, alluser_id: str):
        """Delete an alluser by ID"""
        query = """
        mutation deleteAllUser($id: ID!) {
            deleteAllUser(id: $id) {
                data {
                    id
                }
            }
        }
        """
        variables = {"id": alluser_id}
        return sg.Select_from_table(query, variables)

    def delete_profile(self, sg, profile_id: str):
        """Delete a profile by ID"""
        query = """
        mutation deleteProfile($id: ID!) {
            deleteProfile(id: $id) {
                data {
                    id
                }
            }
        }
        """
        variables = {"id": profile_id}
        return sg.Select_from_table(query, variables)

    def delete_trainee(self, sg, trainee_id: str):
        """Delete a trainee by ID"""
        query = """
        mutation deleteTrainee($id: ID!) {
            deleteTrainee(id: $id) {
                data {
                    id
                }
            }
        }
        """
        variables = {"id": trainee_id}
        return sg.Select_from_table(query, variables)

    def delete_reviewer(self, sg, reviewer_id: str):
        """Delete a reviewer by ID"""
        query = """
        mutation deleteReviewer($id: ID!) {
            deleteReviewer(id: $id) {
                data {
                    id
                }
            }
        }
        """
        variables = {"id": reviewer_id}
        return sg.Select_from_table(query, variables)
    
    
    def request_auth_query(self):
        auth_query = """
                    query {
                        me {
                        id
                username
                email
                role {
                name
                }
            }
            }
            """
        return auth_query
